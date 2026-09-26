"""Self-contained, offline HTML for inspecting technical-spike outputs."""
import base64
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image
from .imaging import to_srgb
from .guidance_view import guidance_html


def data_url(image: Image.Image) -> str:
    buffer = BytesIO()
    to_srgb(image).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def write_report(path: Path, original: Image.Image, *, masks: dict[str, Image.Image],
                 result: Optional[Image.Image] = None, changes: Optional[list[dict]] = None,
                 outcome: str = "preflight") -> None:
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
        compare = f'''<section><h2>Compare the result</h2><p>Move the slider or use the arrow keys.</p>
<div class="compare"><img src="{before}" alt="Original photo"><img id="refined" src="{data_url(result)}"
alt="AI-refined photo"><span id="divider"></span></div>
<label for="position">Refined coverage <output id="coverage">50%</output></label>
<input id="position" type="range" min="0" max="100" value="50" aria-label="Refined image coverage">
<div class="ends"><span>Original only</span><span>Refined only</span></div></section>'''
    instructions = guidance_html(before, changes)
    html = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'">
<title>Makeup Refine · Local inspection</title><style>
*{box-sizing:border-box}body{margin:0;background:#f8f5f2;color:#322a2d;font:16px/1.6 system-ui,sans-serif}
main{max-width:1100px;padding:48px 24px;margin:auto}.eyebrow{color:#98556c;font-size:12px;letter-spacing:.16em;text-transform:uppercase}
h1{font-family:Georgia,serif;font-weight:400;font-size:clamp(32px,5vw,52px);line-height:1.1;margin:12px 0 20px}
h2{font-size:22px;font-weight:500}p{max-width:760px;color:#65575d}.notice{border-left:3px solid #b95d7d;padding:12px 18px;background:#fff}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}figure{margin:0}img{display:block;width:100%;height:auto;border-radius:12px}
figcaption{padding:12px 0;color:#65575d;font-size:14px}section{margin-top:36px}.compare{position:relative;max-width:600px;overflow:hidden;border-radius:12px}
#refined{position:absolute;inset:0;clip-path:inset(0 50% 0 0)}#divider{position:absolute;top:0;bottom:0;left:50%;width:2px;background:white;pointer-events:none}
input{display:block;width:100%;max-width:600px;accent-color:#98556c;min-height:44px}label{display:block;margin-top:12px}output{font-weight:600}.ends{display:flex;justify-content:space-between;max-width:600px;color:#65575d;font-size:13px}
li{margin-bottom:18px}li p{margin-top:4px}footer{border-top:1px solid #ded4d8;margin-top:40px;padding-top:20px;color:#65575d;font-size:13px}
@media(max-width:650px){.grid{grid-template-columns:1fr}main{padding:28px 18px}}
</style><main><div class="eyebrow">Makeup Refine / Technical spike</div>
<h1>A closer look, before the next step.</h1>
'''
    if outcome == "completed_no_changes":
        html += '<p class="notice">No supported refinement was found. The analysis did not identify a confident, useful makeup adjustment. No edited image was generated.</p>'
        html += f'<figure style="max-width:600px"><img src="{before}" alt="Original photo with correct sRGB color"><figcaption>Original · color-managed sRGB</figcaption></figure>'
    elif result is None:
        html += '<p class="notice">Local preflight only. No makeup has been analyzed or changed. Colored areas show candidate edit masks for inspection; they are not recommended adjustments.</p>'
    elif outcome == "technique_demo_requires_review":
        html += '<p class="notice">Placement demo / 位置演示。These are the three requested techniques. Eyeliner and lip-outline intensity still need tuning. 以下展示三处画法，眼线和唇线的浓度还需调整。</p>'
    else:
        html += '<p class="notice">Experimental result. Automated checks do not establish identity preservation, subtlety or realism. Review these before accepting the result.</p>'
    html += compare
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
    if cards:
        html += '<section><h2>Inspect the mask boundaries</h2><p>Check that the highlighted regions follow the makeup areas and exclude eye interiors, teeth and unrelated skin.</p><div class="grid">'
        html += "".join(cards) + '</div></section>'
    html += '<footer>This report stays local and loads no external resources. It contains your photo; delete it with the other trial outputs when finished.</footer></main>'
    if result is not None:
        html += '''<script>const slider=document.getElementById('position');slider.addEventListener('input',()=>{const value=Number(slider.value);document.getElementById('refined').style.clipPath=`inset(0 ${100-value}% 0 0)`;document.getElementById('divider').style.left=`${value}%`;document.getElementById('coverage').textContent=`${value}%`;});</script>'''
    path.write_text(html, encoding="utf-8")
