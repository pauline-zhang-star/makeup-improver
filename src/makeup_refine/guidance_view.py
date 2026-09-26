"""Accessible, offline region selection for the result review."""
from html import escape
import math

LABELS = {'eyeliner': 'Eyeliner / 眼线', 'eyeshadow': 'Eyeshadow / 眼影', 'lips': 'Lips / 唇线'}
COLORS = ['#147daa', '#9444b0', '#b34b29']


def guidance_html(original_data_url, changes):
    if not changes:
        return ''
    buttons, shapes = [], []
    for index, change in enumerate(changes[:3]):
        color = COLORS[index]
        label = LABELS.get(change['area'], change['area'].title())
        chinese = f'<span class="guide-translation">{escape(change["instructionZh"])}</span>' if change.get('instructionZh') else ''
        buttons.append(f'<button type="button" class="guide-choice" data-guide="{index}" aria-pressed="false" style="--guide-color:{color}">'
                       f'<strong>{index+1}. {escape(label)}</strong><span>{escape(change["instruction"])}</span>{chinese}</button>')
        annotations = change.get('annotations', [change.get('annotation', {})])
        polygons = []
        for annotation in annotations:
            points = annotation.get('normalizedPoints', [])
            if len(points) < 3:
                continue
            try:
                numbers = [(float(p[0]), float(p[1])) for p in points]
            except (TypeError, ValueError, IndexError):
                continue
            if not all(math.isfinite(v) and 0 <= v <= 1 for point in numbers for v in point):
                continue
            coords = ' '.join(f'{x},{y}' for x, y in numbers)
            polygons.append(f'<polygon points="{coords}"/>')
        shapes.append(f'<g data-guide-layer="{index}" stroke="{color}" fill="{color}">{"".join(polygons)}</g>')
    return '''<style>
.guide-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(240px,.8fr);gap:24px;align-items:start}
.guide-photo{position:relative;max-width:560px}.guide-photo svg{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.guide-photo polygon{fill-opacity:.13;stroke-width:2;vector-effect:non-scaling-stroke}.guide-photo g{transition:opacity .15s}
.guide-choice,.guide-all{font:inherit;cursor:pointer;text-align:left;background:white;color:#322a2d;border:1px solid #ded4d8;border-radius:10px;padding:14px 16px;min-height:44px}
.guide-choice{display:block;width:100%;margin:0 0 12px;border-left:4px solid var(--guide-color)}
.guide-choice strong,.guide-choice span{display:block}.guide-choice[aria-pressed=true]{outline:2px solid var(--guide-color)}
.guide-choice:focus-visible,.guide-all:focus-visible{outline:3px solid #322a2d;outline-offset:3px}.guide-translation{color:#65575d;font-size:15px}
@media(max-width:650px){.guide-layout{grid-template-columns:1fr}}
</style><section aria-labelledby="guide-heading"><h2 id="guide-heading">How to recreate it / 怎么画</h2>
<p>Choose a step to highlight its area on the original photo. 点选步骤，查看对应位置。</p><div class="guide-layout">
<div class="guide-photo">''' + f'<img src="{original_data_url}" alt="Original photo with highlighted adjustment areas"><svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">{"".join(shapes)}</svg></div>' + \
        '<div>' + ''.join(buttons) + '<button type="button" class="guide-all" data-guide="all" aria-pressed="true">Show all areas / 显示全部</button><p id="guide-status" aria-live="polite">All areas shown / 已显示全部</p></div></div></section>' + '''<script>
const guideButtons=[...document.querySelectorAll('[data-guide]')];
const guideLayers=[...document.querySelectorAll('[data-guide-layer]')];
for(const button of guideButtons){button.addEventListener('click',()=>{
 const selection=button.dataset.guide;
 for(const item of guideButtons){item.setAttribute('aria-pressed',String(item===button));}
 for(const layer of guideLayers){layer.style.opacity=(selection==='all'||layer.dataset.guideLayer===selection)?'1':'0';}
 document.getElementById('guide-status').textContent=selection==='all'?'All areas shown / 已显示全部':button.textContent;
});}
</script>'''
