"""Render observed steps, never the legacy fixed technique instructions."""
from html import escape
from .look_annotations import planned_review_steps


def look_steps_html(report):
    status = report['status']
    if status == 'failed':
        body = '<p>' + escape(report.get('message', 'The image could not be generated.')) + '</p>'
    elif status == 'instructions_unavailable':
        body = '<p>The image is saved. Makeup steps are unavailable; retry the comparison without generating another image.</p>'
    elif status == 'candidate_rejected':
        body = '<p>The candidate moved facial landmarks beyond the allowed limit. No makeup steps were generated.</p>'
    elif status == 'rejected':
        body = '<p>This result changed more than makeup and has not been accepted. No makeup steps are shown.</p>'
    elif status == 'enhanced_ready':
        body = '<p>Your image is ready. Comparing the original and enhanced photos to prepare the steps.</p>'
    elif not report.get('steps'):
        body = '<p>No confident visible makeup changes were identified. No extra steps have been invented.</p>'
    else:
        cards = []
        for number, step in enumerate(report['steps'], 1):
            cards.append(f'<li id="look-step-{number}"><span class="step-number">{number}</span><div><strong>' + escape(step['area'].replace('_', ' ').title()) + '</strong><p>'
                         + escape(step['instruction']) + '</p><details><summary>What changed</summary><p>Before: '
                         + escape(step['before']) + '</p><p>After: ' + escape(step['after']) + '</p></details></div></li>')
        body = '<ol class="look-steps">' + ''.join(cards) + '</ol>'
    planned = planned_review_steps(report)
    if planned:
        body += '<h3>计划技法位置 · 尚未确认生成效果</h3><p>照片上的编号虚线对应以下计划操作；不是对生成结果的确认，也不是已验证的复现指导。</p><ol class="look-steps">'
        for number, item in enumerate(planned, 1):
            body += (f'<li id="look-step-{number}"><span class="step-number">{number}</span><div><strong>'
                     + escape(item['area'] + ' · ' + item['technique_id']) + '</strong><p>'
                     + escape(item['instruction']) + '</p></div></li>')
        body += '</ol>'
    pending = report.get('pendingChangeReviews', [])
    if pending and status not in ('rejected', 'candidate_rejected', 'failed', 'instructions_unavailable'):
        body += '<h3>Changes needing confirmation / 待确认变化</h3><ul>'
        for item in pending:
            body += ('<li><strong>' + escape(item['area']) + '</strong>: ' +
                     escape(item['reason']) + '<br>' + escape(item['before']) + ' → ' +
                     escape(item['after']) + '</li>')
        body += '</ul>'
    return '<section><h2>How to Achieve This Look</h2>' + body + '</section>'


def api_cost_html(report):
    usage = report.get('apiUsage')
    if not usage:
        return '<section><h2>API 费用</h2><p>历史测试未记录 token 用量，费用未知。</p></section>'
    total = usage.get('totalEstimatedUSD')
    headline = (f"估算合计：US${total:.6f}" if total is not None else
                f"已知费用小计：US${usage['knownEstimatedUSD']:.6f}；总费用未知（记录不完整）")
    labels = {'planning': '选技巧', 'generation': '生成图片', 'comparison': '比较并写指导'}
    rows = []
    for stage, group in usage['byStage'].items():
        missing = f"；{group['unpricedCalls']} 次费用未知" if group['unpricedCalls'] else ''
        rows.append('<tr><td>' + escape(labels.get(stage, stage)) + '</td><td>' +
                    str(group['calls']) + '</td><td>US$' + f"{group['knownEstimatedUSD']:.6f}" + missing + '</td></tr>')
    details = []
    for call in usage['calls']:
        tokens = call.get('usage') or {}
        incoming = tokens.get('prompt_tokens', tokens.get('input_tokens', '未知'))
        outgoing = tokens.get('completion_tokens', tokens.get('output_tokens', '未知'))
        cost = '未知' if call['estimatedUSD'] is None else f"US${call['estimatedUSD']:.6f}"
        details.append('<li>' + escape(labels.get(call['stage'], call['stage'])) + ' · ' +
                       escape(call['model']) + f' · 输入 {incoming} / 输出 {outgoing} tokens · ' +
                       cost + ' · ' + escape(call['status']) + ' · 价格日期 ' + escape(call['priceDate']) + '</li>')
    return ('<section><h2>API 费用</h2><p>' + headline + '</p>' +
            ('<p>历史调用用量缺失；仅累计启用记录之后的调用。</p>' if usage['historicalUsageMissing'] else '') +
            '<table><thead><tr><th>步骤</th><th>调用次数</th><th>已知估算费用</th></tr></thead><tbody>' +
            ''.join(rows) + '</tbody></table><details><summary>每次调用的 token 与费用</summary><ul>' +
            ''.join(details) + '</ul></details><p>按记录的公开单价估算，美元、不含税，并非实际账单。'
            'API 返回成功不代表图片通过本地质量检查；被拒绝的成图仍计入。缺失用量不按零元处理。</p></section>')
