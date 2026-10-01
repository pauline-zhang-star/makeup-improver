"""Self-contained, offline HTML for inspecting technical-spike outputs."""
import base64
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image
from .imaging import to_srgb
from .guidance_view import guidance_html
from .look_view import look_steps_html, api_cost_html
from .trial_view import trial_details_html
from .look_annotations import after_annotations_html


def data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    to_srgb(image).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def write_report(path: Path, original: Image.Image, *, masks: dict[str, Image.Image],
                 result: Optional[Image.Image] = None, changes: Optional[list[dict]] = None,
                 outcome: str = "preflight", look_result: Optional[dict] = None) -> None:
    before = data_url(original)
    cards = []
    for area, mask in masks.items():
        # Diagnostic tint only. This never becomes a generated makeup result.
        tint = Image.new("RGB", original.size, "#bc4880")
        overlay = Image.composite(tint, original, mask.point(lambda v: round(v * .48)))
        cards.append(f'<figure><img src="{data_url(overlay)}" alt="{escape(area)} mask overlay">'
                     f'<figcaption>{escape(area.title())} · candidate mask</figcaption></figure>')
    compare = ""
    if result is not None:
        annotations = after_annotations_html(look_result, result.size) if look_result and look_result.get('status') not in ('rejected', 'candidate_rejected', 'failed') else ''
        diagnostic = bool(look_result and (
            look_result.get('status') in ('candidate_rejected', 'rejected') or
            (look_result.get('enhancedImage') is None and
             (look_result.get('alignedCandidateImage') or look_result.get('candidateImage')))))
        after_alt = 'Rejected candidate for inspection only' if diagnostic else 'AI-refined photo'
        coverage_label = 'Candidate shown' if diagnostic else 'Refined coverage'
        end_label = 'Rejected candidate only' if diagnostic else 'Refined only'
        compare = f'''<section data-comparison><h2>Compare the result</h2><p>Move the slider or use the arrow keys.</p>
<div class="compare"><img src="{before}" alt="Original photo"><div id="refined" data-refined><img src="{data_url(result)}"
alt="{after_alt}">{annotations}</div><span id="divider" data-divider></span></div>
<label for="position">{coverage_label} <output id="coverage" data-coverage>50%</output></label>
<input id="position" type="range" min="0" max="100" value="50" aria-label="{coverage_label}">
<div class="ends"><span>Original only</span><span>{end_label}</span></div></section>'''
    instructions = look_steps_html(look_result) if look_result is not None else guidance_html(before, changes)
    html = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Makeup Refine · Local inspection</title><style>
*{box-sizing:border-box}body{margin:0;background:#f8f5f2;color:#322a2d;font:16px/1.6 system-ui,sans-serif}
main{max-width:1100px;padding:48px 24px;margin:auto}.eyebrow{color:#98556c;font-size:12px;letter-spacing:.16em;text-transform:uppercase}
h1{font-family:Georgia,serif;font-weight:400;font-size:clamp(32px,5vw,52px);line-height:1.1;margin:12px 0 20px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#fff;padding:14px;font-size:13px}summary{cursor:pointer}table{border-collapse:collapse}td,th{padding:8px;text-align:left}h2{font-size:22px;font-weight:500}p{max-width:760px;color:#65575d}.notice{border-left:3px solid #b95d7d;padding:12px 18px;background:#fff}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}figure{margin:0}img{display:block;width:100%;height:auto;border-radius:12px}
figcaption{padding:12px 0;color:#65575d;font-size:14px}section{margin-top:36px}.compare{position:relative;max-width:600px;overflow:hidden;border-radius:12px;touch-action:pan-y;user-select:none}.compare img{pointer-events:none}
[data-refined]{position:absolute;inset:0;clip-path:inset(0 50% 0 0)}[data-divider]{position:absolute;top:0;bottom:0;left:50%;width:2px;background:white;pointer-events:none}
.after-annotations,.after-annotations svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.callout-line,.callout-halo{vector-effect:non-scaling-stroke;fill:none;stroke-dasharray:4 4;stroke-linecap:round}.callout-line{stroke:#842e59;stroke-width:1.6}.callout-halo{stroke:white;stroke-width:3.8;stroke-opacity:.9}
.callout-number,.step-number{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;background:#842e59;color:white;font:bold 12px/1 system-ui,sans-serif;border:1.5px solid white;box-shadow:0 1px 3px #0005}
.callout-number{position:absolute;transform:translate(-50%,-50%)}.look-steps{list-style:none;padding:0}.look-steps li{display:flex;gap:12px;align-items:flex-start}.step-number{flex:none;margin-top:2px}.look-steps li p{margin-top:4px}
input{display:block;width:100%;max-width:600px;accent-color:#98556c;min-height:44px}label{display:block;margin-top:12px}output{font-weight:600}.ends{display:flex;justify-content:space-between;max-width:600px;color:#65575d;font-size:13px}
li{margin-bottom:18px}li p{margin-top:4px}footer{border-top:1px solid #ded4d8;margin-top:40px;padding-top:20px;color:#65575d;font-size:13px}
@media(max-width:650px){.grid{grid-template-columns:1fr}main{padding:28px 18px}}
</style><main><div class="eyebrow">Makeup Refine / Technical spike</div>
<h1>A closer look, before the next step.</h1>
'''
    if look_result is not None:
        html = html.replace('A closer look, before the next step.', 'Your makeup look')
        html += '<p>Style: ' + escape(look_result.get('requestedStyle', 'Auto')) + '</p>'
        candidate_only = (look_result.get('enhancedImage') is None and
                          (look_result.get('alignedCandidateImage') or look_result.get('candidateImage')))
        if look_result['status'] == 'candidate_rejected' or candidate_only:
            html += '<p class="notice">Rejected candidate shown for comparison only. It failed an automated quality check and is not an accepted enhanced image. / 下方滑块显示未通过自动质量检查的候选图，仅供测试对比，不是已接受的增强结果。</p>'
        elif look_result['status'] == 'rejected':
            html += '<p class="notice">The generated result needs review because changes beyond makeup were detected.</p>'
            html += '<p>未通过视觉检查，仍显示滑动对比供测试。</p>'
        else:
            html += '<p class="notice">Review the result for likeness and makeup quality. Automated checks cannot guarantee either.</p>'
            if result is None:
                html += f'<figure style="max-width:600px"><img src="{before}" alt="Original photo"></figure>'
    elif outcome == "completed_no_changes":
        html += '<p class="notice">No supported refinement was found. The analysis did not identify a confident, useful makeup adjustment. No edited image was generated.</p>'
        html += f'<figure style="max-width:600px"><img src="{before}" alt="Original photo with correct sRGB color"><figcaption>Original · color-managed sRGB</figcaption></figure>'
    elif result is None:
        html += '<p class="notice">Local preflight only. No makeup has been analyzed or changed. Colored areas show candidate edit masks for inspection; they are not recommended adjustments.</p>'
    elif outcome == "technique_demo_requires_review":
        html += '<p class="notice">Placement demo / 位置演示。These are the three requested techniques. Eyeliner and lip-outline intensity still need tuning. 以下展示三处画法，眼线和唇线的浓度还需调整。</p>'
    else:
        html += '<p class="notice">Experimental result. Automated checks do not establish identity preservation, subtlety or realism. Review these before accepting the result.</p>'
    html += compare
    if look_result is not None:
        html += trial_details_html(look_result, path.parent)
        # Every returned attempt remains independently inspectable, even if a later one passed.
        for attempt in look_result.get('generationAttempts', []):
            number = attempt['attempt']
            if not isinstance(number, int) or number < 1:
                continue
            for kind, label in ((f'candidate-{number}.png', 'API 候选图'),
                                (f'aligned-candidate-{number}.png', '对齐与合成后')):
                candidate_path = path.parent / kind
                if not candidate_path.exists():
                    continue
                with Image.open(candidate_path) as candidate:
                    html += comparison_panel(before, data_url(candidate),
                        f"第 {number} 次 · {label} · {attempt['status']}")
    if instructions:
        html += instructions
    if result is not None and masks:
        bounds = [mask.getbbox() for mask in masks.values() if mask.getbbox()]
        if bounds:
            margin = 24
            box = (max(0, min(b[0] for b in bounds) - margin),
                   max(0, min(b[1] for b in bounds) - margin),
                   min(original.width, max(b[2] for b in bounds) + margin),
                   min(original.height, max(b[3] for b in bounds) + margin))
            html += '<section><h2>Adjustment close-up</h2><p>Matching crops, at the same scale and in the same color space.</p><div class="grid" style="grid-template-columns:repeat(2,1fr)">'
            for label, photo in (("Original", original), ("Refined", result)):
                html += f'<figure><img src="{data_url(photo.crop(box))}" alt="{label} adjustment close-up"><figcaption>{label}</figcaption></figure>'
            html += '</div></section>'
    if look_result is not None:
        html += api_cost_html(look_result)
    if cards:
        html += '<section><h2>Inspect the mask boundaries</h2><p>Check that the highlighted regions follow the makeup areas and exclude eye interiors, teeth and unrelated skin.</p><div class="grid">'
        html += "".join(cards) + '</div></section>'
    html += '<footer>This report stays local and loads no external resources. It contains your photo; delete it with the other trial outputs when finished.</footer></main>'
    if result is not None or (look_result and look_result.get('generationAttempts')):
        html += '''<script>document.querySelectorAll('[data-comparison]').forEach(panel=>{
const slider=panel.querySelector('input[type="range"]');const compare=panel.querySelector('.compare');
const update=()=>{const value=Number(slider.value);panel.querySelector('[data-refined]').style.clipPath=`inset(0 ${100-value}% 0 0)`;panel.querySelector('[data-divider]').style.left=`${value}%`;panel.querySelector('[data-coverage]').textContent=`${value}%`;};
slider.addEventListener('input',update);
const move=(event)=>{const rect=compare.getBoundingClientRect();slider.value=String(Math.round(Math.max(0,Math.min(100,(event.clientX-rect.left)/rect.width*100))));update();};
compare.addEventListener('pointerdown',event=>{if(event.button!==0)return;compare.setPointerCapture(event.pointerId);move(event);});
compare.addEventListener('pointermove',event=>{if(compare.hasPointerCapture(event.pointerId))move(event);});
compare.addEventListener('pointerup',event=>{if(compare.hasPointerCapture(event.pointerId))compare.releasePointerCapture(event.pointerId);});
});</script>'''
    path.write_text(html, encoding="utf-8")


def comparison_panel(before, after, title):
    return ('<details><summary>' + escape(title) + '</summary><section data-comparison>'
            '<p>点击照片定位，按住拖动。候选图仅供检查，不代表最终接受。</p>'
            '<div class="compare"><img src="' + before + '" alt="Original photo">'
            '<div data-refined><img src="' + after + '" alt="Candidate for inspection"></div>'
            '<span data-divider></span></div><label>候选图显示比例 <output data-coverage>50%</output>'
            '<input type="range" min="0" max="100" value="50" aria-label="Candidate coverage">'
            '</label></section></details>')
