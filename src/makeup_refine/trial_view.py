"""Human-readable local audit of a test, alongside its immutable artifacts."""
import json
from html import escape


def details(label, value):
    return '<details><summary>' + escape(label) + '</summary><pre>' + escape(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre></details>'


def trial_details_html(report, directory=None):
    plan = report.get('techniquePlan') or {}
    body = '<section><h2>测试流程记录</h2><p>状态：' + escape(report['status']) + '</p>'
    if report.get('message'):
        body += '<p class="notice">' + escape(report['message']) + '</p>'
    if report.get('inputQuality'):
        body += details('上传照片局部细节检查（试验阈值）', report['inputQuality'])
    body += '<h3>1. 技法选择与依据</h3>'
    body += '<p>' + escape(plan.get('look_direction', '尚无已验证方案')) + '</p>'
    for item in plan.get('selected', []):
        body += '<details open><summary>' + escape(item['technique_id'] + ' · ' + item['region']) + '</summary>'
        for label, key in [('原图观察', 'observation'), ('选择依据', 'style_reason'), ('计划操作', 'application')]:
            body += '<p>' + label + '：' + escape(item.get(key, '历史记录未提供')) + '</p>'
        if item.get('structured_evidence'):
            body += details('结构化依据（模型观察，不是独立视觉证明）', item['structured_evidence'])
        body += details('强度、相对色彩变化和完整技法数据', item) + '</details>'
    body += details('模型原始分析（不是已确认的图像变化）', report.get('techniqueAnalysis', '未记录或尚未完成'))
    body += '<h3>2. 技法合法性检查</h3>'
    body += details('逐项检查结果与首个失败原因', plan.get('validation_results') or '历史记录未提供逐项检查')
    body += details('被过滤的技法', plan.get('rejected_proposals', []))
    body += details('保留不动的部位', plan.get('preserved_areas', []))
    body += '<h3>3. 实际 API 请求与返回</h3><p>保存实际发送的提示词和参数；图片以文件路径、SHA-256 和原始字节保存。未保存认证请求头。</p>'
    calls = report.get('apiTrace', [])
    if not calls:
        body += '<p>尚无请求记录；历史测试不能还原实际请求。</p>'
    for i, call in enumerate(calls, 1):
        body += '<details><summary>' + escape(f"调用 {i} · {call['stage']} · {call['model']} · {call['status']}") + '</summary>'
        body += details('实际发送内容', call.get('requestPayload'))
        if directory is not None:
            body += input_previews(call.get('requestPayload'), directory)
        body += details('实际返回内容（图片字节单独保存）', call.get('responsePayload')) + '</details>'
    body += '<h3>4. 每次出图的检查结果</h3>'
    for attempt in report.get('generationAttempts', []):
        body += '<details open><summary>' + escape(f"第 {attempt['attempt']} 次 · {attempt['status']}") + '</summary>'
        if attempt.get('message'):
            body += '<p class="notice">' + escape(attempt['message']) + '</p>'
        for name, check in attempt.get('checks', {}).items():
            body += '<p>' + escape(name + '：' + check['status']) + '</p>'
            if check.get('message'):
                body += '<p>' + escape(check['message']) + '</p>'
        body += details('检查数值、偏移及所有诊断数据', attempt) + '</details>'
    if report.get('localPixelGeometryRecheck'):
        body += details('新像素测量本地复核（保留原始检查记录）', report['localPixelGeometryRecheck'])
    if report.get('mouthWidthReview'):
        body += details('唇宽 ±8% 待复核规则', report['mouthWidthReview'])
    body += '<h3>5. 最终对比与操作指导核对</h3>'
    body += details('逐部位视觉判断', report.get('assessments', []))
    body += details('局部像素证据', report.get('comparisonEvidence'))
    body += details('五官或其他非妆容变化', report.get('preservationIssues', []))
    body += details('未确认变化', report.get('pendingChangeReviews', []))
    body += '<p>not_run 表示此前步骤已停止，不能当作检查通过。费用明细在下方。</p></section>'
    return body


def input_previews(payload, directory):
    from PIL import Image
    import base64
    refs = []
    def visit(value):
        if isinstance(value, dict):
            if 'file' in value and 'sha256' in value:
                refs.append(value['file'])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(payload)
    images = []
    for ref in dict.fromkeys(refs):
        path = (directory / ref).resolve()
        if directory.resolve() not in path.parents:
            continue
        try:
            with Image.open(path) as image:
                images.append('<figure><img src="' + ('data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode()) + '" alt="Actual API input">'
                              '<figcaption>' + escape(ref) + f' · {image.width}×{image.height}</figcaption></figure>')
        except (OSError, ValueError):
            continue
    return '<details><summary>实际输入图片 / 遮罩 / 局部对照</summary><div class="grid">' + ''.join(images) + '</div></details>' if images else ''
