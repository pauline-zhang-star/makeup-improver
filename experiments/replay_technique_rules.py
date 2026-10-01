"""Offline audit of saved analysis against current rules; never calls a provider.

Run: PYTHONPATH=src .venv/bin/python experiments/replay_technique_rules.py
All patient/photo-derived outputs stay under ignored outputs/.
"""
import argparse
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from makeup_refine.look_models import MakeupStyle
from makeup_refine.technique_catalog import (
    MIN_CONFIDENCE, Measurement, TechniqueAnalysis, TechniqueCatalog,
    STYLE_SIGNATURE_PRIORITY, STYLE_BASELINE_FALLBACKS,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def condition_trace(catalog, condition, analysis, overrides=None):
    """Expand every AND/OR leaf, including those hidden by short-circuiting."""
    overrides = overrides or {}
    if not condition:
        return {'operator': 'none', 'passed': None, 'leaves': []}
    if 'all_of' in condition:
        children = [condition_trace(catalog, part, analysis, overrides)
                    for part in condition['all_of']]
        result = {'operator': 'AND', 'passed': all(c['passed'] for c in children),
                  'leaves': [leaf for c in children for leaf in c['leaves']]}
    elif isinstance(condition['feature'], list):
        assert condition['comparator'] == 'matches_downturned_or_elongated'
        children = [condition_trace(catalog, {'feature': key, 'comparator': 'below_threshold'},
                                    analysis, overrides) for key in condition['feature']]
        result = {'operator': 'OR', 'passed': any(c['passed'] for c in children),
                  'leaves': [leaf for c in children for leaf in c['leaves']]}
    else:
        feature, comparator = condition['feature'], condition['comparator']
        m = analysis.lighting_gate if feature == 'lighting_gate' else analysis.measurements.get(feature)
        threshold = overrides.get(feature, {}).get(comparator,
                    catalog.thresholds.get(feature, {}).get(comparator))
        default = catalog.thresholds.get(feature, {}).get(comparator)
        value = m.value if m else None
        margin = None
        if m is None:
            reason = 'missing_measurement'
        elif m.detection_confidence < MIN_CONFIDENCE:
            reason = 'low_confidence'
        elif comparator in ('true', 'pass'):
            reason = 'passed' if value is True else 'boolean_false'
        elif threshold is None:
            reason = 'missing_threshold'
        elif isinstance(value, bool):
            reason = 'invalid_numeric_value'
        else:
            margin = threshold - value if comparator == 'below_threshold' else value - threshold
            reason = 'passed' if margin > 0 else 'threshold_not_met'
        result = {'operator': 'leaf', 'passed': reason == 'passed', 'leaves': [{
            'feature': feature, 'value': value,
            'confidence': m.detection_confidence if m else None,
            'minimum_confidence': MIN_CONFIDENCE, 'comparator': comparator,
            'auto_threshold': default, 'effective_threshold': threshold,
            'override_applied': comparator in overrides.get(feature, {}),
            'signed_margin': margin, 'reason': reason,
        }]}
    # This assertion checks the audit against the production predicate.
    assert result['passed'] == (catalog._check(condition, analysis, overrides) is not None)
    return result


def image_key(folder):
    for name in ('originalImage.png', 'original.png'):
        p = folder / name
        if p.exists():
            with Image.open(p) as image:
                image = image.convert('RGB')
                return hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
    return None


def audit(source, destination):
    catalog = TechniqueCatalog()
    rows, inventory = [], []
    for p in sorted(source.rglob('result.json')):
        if destination == p.parent or destination in p.parents:
            continue
        data = json.loads(p.read_text())
        raw = data.get('techniqueAnalysis')
        info = {'run': p.parent.name, 'source': str(p.resolve()),
                'historical_style': data.get('requestedStyle', 'Auto'),
                'historical_status': data.get('status'),
                'analysis_reused_from': data.get('analysisReusedFrom')}
        if not raw:
            inventory.append({**info, 'audit_status': 'no_saved_analysis'})
            continue
        if raw.get('analysis_schema') == 'model_visual_reasoning_v1':
            inventory.append({**info, 'audit_status': 'unsupported_model_reasoning_schema'})
            continue
        try:
            analysis = TechniqueAnalysis.model_validate({k: v for k, v in raw.items()
                                                        if k in TechniqueAnalysis.model_fields})
        except Exception as exc:
            inventory.append({**info, 'audit_status': 'invalid_analysis', 'error': str(exc)})
            continue
        normalizations = []
        if raw.get('visibility') != {k: v.model_dump() for k, v in analysis.visibility.items()}:
            normalizations.append('current_schema_normalized_visibility; see saved_analysis.json')
        if 'brow_visibility' not in analysis.measurements and 'brows' in analysis.visibility:
            v = analysis.visibility['brows']
            analysis.measurements['brow_visibility'] = Measurement(
                value=1.0 if v.value is True else 0.0, detection_confidence=v.detection_confidence)
            normalizations.append('brow_visibility_derived_from_saved_region_visibility')
        fingerprint = digest({k: raw.get(k) for k in ('measurements', 'visibility', 'lighting_gate')})
        photo = image_key(p.parent)
        info.update(audit_status='replayed', analysis_hash=fingerprint, image_hash=photo,
                    normalizations=normalizations, historical_catalog_version=data.get('techniquePlan', {}).get('catalog_version'),
                    historical_selected=data.get('selectedTechniques',
                        [v['technique_id'] for v in data.get('techniquePlan', {}).get('selected', [])]))
        inventory.append(info)
        for style in MakeupStyle:
            completed = catalog.complete_placement_proposals(analysis, style)
            selection = catalog.select(completed, style)
            selected = {v['technique_id']: v for v in selection.selected}
            proposals = {v.technique_id: v for v in completed.proposals}
            for tid, (region, entry) in catalog.entries.items():
                overrides = catalog.trigger_overrides_for_style(style).get(tid, {})
                trigger = condition_trace(catalog, entry.get('trigger'), analysis, overrides)
                auto = condition_trace(catalog, entry.get('trigger'), analysis)
                recipe = tid in STYLE_SIGNATURE_PRIORITY.get(style, ())
                baseline = bool(entry.get('style_baseline')) or style.value in entry.get('style_baseline_styles', [])
                fallback = tid in STYLE_BASELINE_FALLBACKS and not trigger['passed']
                bypasses = [label for label, active in [('recipe', recipe), ('baseline', baseline),
                            ('fallback', fallback and not baseline and not recipe)] if active]
                visible = analysis.visibility.get(region)
                blockers = []
                if entry.get('enabled') is False:
                    blockers.append('disabled')
                if visible is None:
                    blockers.append('missing_visibility')
                elif visible.value is not True:
                    blockers.append('region_not_visible')
                elif visible.detection_confidence < MIN_CONFIDENCE:
                    blockers.append('visibility_low_confidence')
                guards = []
                regional = catalog.data['regions'][region].get('visibility_precondition')
                if regional:
                    guards.append(('regional_precondition', regional))
                if entry.get('reference_color_source') == 'hair_detection':
                    guards.append(('hair_detection', {'feature': 'hair_detection_confidence', 'comparator': 'above_threshold'}))
                if tid in catalog.data['hue_shift_entries_gated_by_lighting_check']:
                    guards.append(('lighting', {'feature': 'lighting_gate', 'comparator': 'pass'}))
                guard_results = []
                for label, guard in guards:
                    trace = condition_trace(catalog, guard, analysis, overrides)
                    guard_results.append({'stage': label, **trace})
                    if not trace['passed']:
                        blockers.append(label)
                proposal = proposals.get(tid)
                if proposal is None:
                    blockers.append('no_proposal')
                elif catalog._strength(proposal, entry, region) is None:
                    blockers.append('invalid_or_excessive_strength')
                rows.append({
                    'run': info['run'], 'analysis_hash': fingerprint, 'image_hash': photo,
                    'historical_style': info['historical_style'], 'replay_style': style.value,
                    'technique_id': tid, 'region': region, 'technique': entry['technique'],
                    'historically_selected': tid in info['historical_selected'],
                    'current_selected': tid in selected,
                    'selection_basis': selected.get(tid, {}).get('selection_basis'),
                    'trigger': trigger, 'auto_trigger_passed': auto['passed'],
                    'override_changed_trigger_outcome': trigger['passed'] != auto['passed'],
                    'bypass_paths': bypasses,
                    'selected_without_passing_trigger': tid in selected and trigger['passed'] is not True,
                    'guards': guard_results, 'other_blockers': blockers,
                    'evidence_eligible_without_bypass': trigger['passed'] is True and not blockers,
                    'visibility': visible.model_dump() if visible else None,
                })
    destination.mkdir(parents=True, exist_ok=True)
    metadata = {'generated_at': datetime.now(timezone.utc).isoformat(),
                'selection_mode': 'legacy_threshold_recipe_audit',
                'code_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'catalog_version': catalog.data['table_version'],
                'source_reports': len(inventory),
                'saved_analyses': sum(v['audit_status'] == 'replayed' for v in inventory),
                'unique_analysis_snapshots': len({v['analysis_hash'] for v in inventory if 'analysis_hash' in v}),
                'unique_exact_image_hashes': len({v['image_hash'] for v in inventory if v.get('image_hash')}),
                'technique_rows': len(rows), 'styles_replayed': [s.value for s in MakeupStyle],
                'notes': ['Replay uses the retained legacy threshold/recipe engine, not the production model planner.',
                    'current_selected means this retained legacy selector, not a fresh model decision.',
                    'Cross-style replay reuses saved measurements; it is not a new style-conditioned analysis.',
                    'Image hashes group identical decoded pixels only; resized copies can have different hashes.',
                    'Saved analyses can already include landmark/visibility postprocessing and cached/synthetic data.',
                    'Model confidence is self-reported, not calibrated accuracy.',
                    'Selection pass is not proof of visual quality or actual generated change.',
                    'signed_margin > 0 passes a numeric gate; equality fails strict inequalities.',
                    'No thresholds or product behavior were modified; no provider or detector was called.']}
    (destination / 'audit.json').write_text(json.dumps({'metadata': metadata, 'inventory': inventory, 'rows': rows}, indent=2, ensure_ascii=False))
    # Keep full source snapshots for examining preprocessing/proposal provenance.
    (destination / 'saved_analysis.json').write_text(json.dumps({v['run']: json.loads(Path(v['source']).read_text())['techniqueAnalysis']
        for v in inventory if v['audit_status'] == 'replayed'}, indent=2, ensure_ascii=False))
    (destination / 'rules_snapshot.json').write_text(json.dumps({'catalog': catalog.data, 'thresholds': catalog.thresholds,
        'overrides': {s.value: catalog.trigger_overrides_for_style(s) for s in MakeupStyle}}, indent=2, ensure_ascii=False))
    fields = ['run', 'historical_style', 'replay_style', 'technique_id', 'region', 'stage', 'operator', 'feature',
        'value', 'confidence', 'minimum_confidence', 'comparator', 'auto_threshold', 'effective_threshold',
        'override_applied', 'signed_margin', 'reason', 'trigger_passed', 'auto_trigger_passed',
        'current_selected', 'historically_selected', 'bypass_paths', 'other_blockers']
    with (destination / 'conditions.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fields); writer.writeheader()
        for row in rows:
            for trace in [{'stage': 'technique_trigger', **row['trigger']}] + row['guards']:
                for leaf in trace['leaves'] or [{'reason': 'no_trigger_defined'}]:
                    flat = {k: row[k] for k in fields if k in row}
                    flat.update(leaf, stage=trace['stage'], operator=trace['operator'], trigger_passed=row['trigger']['passed'])
                    for k in ['bypass_paths', 'other_blockers']:
                        flat[k] = ';'.join(flat[k])
                    writer.writerow(flat)
    write_summary(destination, metadata, inventory, rows)
    render_report(destination, metadata, inventory, rows)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


def write_summary(destination, metadata, inventory, rows):
    unique = {}
    for row in rows:
        unique.setdefault((row['analysis_hash'], row['replay_style'], row['technique_id']), row)
    groups = defaultdict(list)
    for row in unique.values():
        if any(leaf['override_applied'] for leaf in row['trigger']['leaves']):
            groups[(row['replay_style'], row['technique_id'])].append(row)
    summary = []
    for (style, tid), group in groups.items():
        summary.append({'style': style, 'technique_id': tid, 'snapshots': len(group),
            'auto_trigger_pass': sum(r['auto_trigger_passed'] is True for r in group),
            'style_trigger_pass': sum(r['trigger']['passed'] is True for r in group),
            'newly_passed': sum(r['trigger']['passed'] is True and r['auto_trigger_passed'] is False for r in group),
            'newly_failed': sum(r['trigger']['passed'] is False and r['auto_trigger_passed'] is True for r in group),
            'failed_with_missing_measurement': sum(not r['trigger']['passed'] and any(l['reason'] == 'missing_measurement' for l in r['trigger']['leaves']) for r in group),
            'failed_with_low_confidence': sum(not r['trigger']['passed'] and any(l['reason'] == 'low_confidence' for l in r['trigger']['leaves']) for r in group)})
    with (destination / 'override_summary.csv').open('w', newline='') as f:
        fields = ['style', 'technique_id', 'snapshots', 'auto_trigger_pass', 'style_trigger_pass',
                  'newly_passed', 'newly_failed', 'failed_with_missing_measurement', 'failed_with_low_confidence']
        writer = csv.DictWriter(f, fields); writer.writeheader(); writer.writerows(summary)
    lines = ['# 历史测量的离线阈值回放', '',
        f"当前代码 `{metadata['code_commit'][:7]}`，技法表 {metadata['catalog_version']}。",
        f"扫描 {metadata['source_reports']} 份结果，{metadata['saved_analyses']} 份有分析，"
        f"去重后 {metadata['unique_analysis_snapshots']} 份不同测量快照；原图按相同像素分为 {metadata['unique_exact_image_hashes']} 组。",
        f"{sum(v['audit_status'] == 'no_saved_analysis' for v in inventory)} 份没有保存分析的结果不能判断触发原因；完整清单见 audit.json 的 inventory。", '',
        '**下面的分母是不同测量快照，不是独立照片或独立受试者；跨风格只是同一保存数据的反事实回放。**',
        '表中统计只判断技法触发条件，不代表区域安全门槛、实际选中、生成成功或审美提升。', '',
        '| 风格 | 技法 | Auto 通过 | 风格通过 | 新增通过 | 转为失败 | 失败含缺测 | 失败含低置信度 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for s in summary:
        lines.append(f"| {s['style']} | {s['technique_id']} | {s['auto_trigger_pass']}/{s['snapshots']} | {s['style_trigger_pass']}/{s['snapshots']} | {s['newly_passed']} | {s['newly_failed']} | {s['failed_with_missing_measurement']} | {s['failed_with_low_confidence']} |")
    lines += ['', '## 同一原图保存值的范围', '',
        '这些是跨历史版本、提示词和设置的保存值范围，不能直接当作同条件重复性实验。',
        '仍可说明：阈值之外还需检查测量和预处理的一致性。', '',
        '| 原图像素哈希（示例记录） | 折痕可见度 | 唇肤色对比 | 眉边缘清晰度 |',
        '|---|---|---|---|']
    images = defaultdict(list)
    for item in inventory:
        if item.get('image_hash'):
            images[item['image_hash']].append(item)
    for key, records in images.items():
        spans = []
        for feature in ('crease_visibility', 'lip_skin_contrast_ratio', 'brow_edge_definition'):
            vals = []
            for item in records:
                raw = json.loads(Path(item['source']).read_text())['techniqueAnalysis']
                if feature in raw['measurements']:
                    vals.append(raw['measurements'][feature]['value'])
            spans.append(f'{min(vals):.3f}–{max(vals):.3f}' if vals else '缺测')
        lines.append(f"| {key[:8]} ({records[0]['run']}) | {' | '.join(spans)} |")
    lines += ['', '## 阅读说明', '',
        '- conditions.csv：逐条件原值、置信度、Auto／风格阈值、严格不等式余量、失败原因、绕过路径及入选状态。',
        '- audit.json：每项 AND／OR 组合结论、可见性、附加门槛、强度／提案检查、历史与当前选中情况。',
        '- recipe 和 baseline 的绕过路径都单独记录；可见性通过不等于技法触发通过。',
        '- historical_selected 是历史原风格的实际入选；current_selected 是当前代码在指定回放风格下重新选择。',
        '- 当前模型解析器可规范化可见性，缺少的 brow_visibility 可由保存的区域可见性派生；inventory 标记了这些操作。',
        '- 没有重新运行关键点检测。输入值可能已被历史预处理修改，原始模型值不完整时不能倒推出来源。',
        '- override 不是全部放宽：Natural 的 lips_04 从 >0.72 到 >0.80、Work 的 brow_04 从 >0.72 到 >0.78 都是收紧。',
        '- 不能仅凭这些触发计数推断没有美感提升空间，也不能据此确定最佳新阈值。',
        '- 没有调用 API，也没有修改生产阈值、选技法逻辑或已有结果。', '']
    (destination / 'summary.md').write_text('\n'.join(lines), encoding='utf-8')


def render_report(destination, metadata, inventory, rows):
    payload = json.dumps({'metadata': metadata, 'inventory': inventory, 'rows': rows}, ensure_ascii=False).replace('<', '\\u003c')
    template = '''<!doctype html><meta charset="utf-8"><title>技法阈值离线回放</title>
<style>body{font:15px/1.6 system-ui;margin:28px;color:#28222b;background:#faf8f5}h1{font-size:26px}p{max-width:1100px}select,input{font:inherit;padding:7px;margin:5px}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border:1px solid #ddd;text-align:left;vertical-align:top}th{background:#eee8e4;position:sticky;top:0}.bad{color:#9f3030}.good{color:#186340}details{min-width:300px}code{font-size:12px}.note{background:#fff0cf;padding:12px}small{color:#655c62}.scroll{overflow:auto}</style>
<h1>技法阈值离线回放</h1><p id="stats"></p>
<p class="note">使用当前规则回放历史测量，不能重现当时版本的完整选择过程。跨风格使用同一份保存测量，不代表重新分析了照片。重复测试和缓存不算独立样本；本报告没有生成图片、修改阈值或判断哪种妆容更好。</p>
<p>展开每项可查看所有 AND／OR 分支、置信度和其他门槛。数值余量为正才通过；0 表示刚好卡在边界，仍不通过。历史入选属于原测试风格，当前入选属于下方选择的回放风格。</p>
<label>记录<select id="run"></select></label><label>回放风格<select id="style"></select></label>
<label>技法<input id="search" placeholder="例如 brow 或 lips_01"></label>
<label>显示<select id="mode"><option value="all">所有技法</option><option value="bypass">当前入选但无技法触发依据</option><option value="override">风格 override 涉及项</option><option value="changed">override 改变触发结论</option></select></label>
<p id="count"></p><div class="scroll"><table><thead><tr><th>记录／技法</th><th>Auto → 风格触发</th><th>绕过路径</th><th>当前／历史入选</th><th>逐项记录</th></tr></thead><tbody id="body"></tbody></table></div>
<p><a href="summary.md">汇总与测量波动</a> · <a href="override_summary.csv">override 汇总 CSV</a> · <a href="conditions.csv">逐条件 CSV</a> · <a href="audit.json">完整 JSON（含未能回放记录）</a> · <a href="rules_snapshot.json">规则快照</a> · <a href="saved_analysis.json">保存的分析快照</a></p>
<script type="application/json" id="data">PAYLOAD</script><script>
const d=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const yn=v=>v===null?'无触发定义':v?'通过':'未通过';
const reasons={passed:'通过',missing_measurement:'缺少测量',low_confidence:'置信度不足',threshold_not_met:'未达到阈值',missing_threshold:'未定义阈值',boolean_false:'布尔条件不满足',invalid_numeric_value:'数值类型错误'};
$('stats').textContent=`${d.metadata.source_reports} 份结果 · ${d.metadata.saved_analyses} 份可回放分析 · ${d.metadata.unique_analysis_snapshots} 份不同测量快照 · ${d.metadata.unique_exact_image_hashes} 组完全相同像素的原图 · ${d.metadata.technique_rows} 条技法记录`;
$('run').innerHTML='<option value="">全部记录</option>'+d.inventory.filter(x=>x.audit_status==='replayed').map(x=>`<option>${esc(x.run)}</option>`).join('');
$('style').innerHTML='<option value="historical">每份记录当时选择的风格</option>'+d.metadata.styles_replayed.map(x=>`<option>${esc(x)}</option>`).join('');
function render(){const a=d.rows.filter(r=>(!$('run').value||r.run===$('run').value)&&r.replay_style===($('style').value==='historical'?r.historical_style:$('style').value)&&(`${r.technique_id} ${r.region}`.includes($('search').value.toLowerCase()))&&($('mode').value==='all'||$('mode').value==='bypass'&&r.selected_without_passing_trigger||$('mode').value==='override'&&r.trigger.leaves.some(l=>l.override_applied)||$('mode').value==='changed'&&r.override_changed_trigger_outcome));
$('count').textContent=`${a.length} 项；当前入选但未通过技法触发 ${a.filter(r=>r.selected_without_passing_trigger).length} 项（含没有定义触发条件的 baseline）。`;
$('body').innerHTML=a.map(r=>`<tr><td><small>${esc(r.run)}<br>${esc(r.replay_style)}</small><br><b>${esc(r.technique_id)}</b> ${esc(r.region)}</td><td>${yn(r.auto_trigger_passed)} → <b class="${r.trigger.passed?'good':'bad'}">${yn(r.trigger.passed)}</b></td><td>${esc(r.bypass_paths.join(', ')||'无')}<br><small>仅代表代码路径，不保证最终入选</small></td><td>${r.current_selected?'是':'否'} / ${r.historically_selected?'是':'否'}<br>${esc(r.selection_basis)}</td><td><details><summary>展开 ${r.trigger.operator} 条件及其他门槛</summary>${[{stage:'技法触发',...r.trigger},...r.guards].map(t=>`<b>${esc(t.stage)} (${t.operator})</b>${t.leaves.map(l=>`<p><code>${esc(l.feature)}</code>: ${esc(l.value)} · 置信度 ${esc(l.confidence)}<br>${esc(l.comparator)} · Auto ${esc(l.auto_threshold)} → 当前 ${esc(l.effective_threshold)}<br>余量 ${l.signed_margin===null?'—':l.signed_margin.toFixed(5)} · ${esc(reasons[l.reason]||l.reason)}</p>`).join('')}`).join('')}<p>其他阻挡：${esc(r.other_blockers.join(', ')||'无')}<br>区域可见性：${esc(JSON.stringify(r.visibility))}</p></details></td></tr>`).join('');}
for(const id of ['run','style','search','mode'])$(id).addEventListener('input',render);render();</script>'''
    (destination / 'index.html').write_text(template.replace('PAYLOAD', payload), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('outputs'))
    parser.add_argument('--output', type=Path, default=Path('outputs/threshold-replay-20260930'))
    args = parser.parse_args()
    audit(args.source, args.output)
