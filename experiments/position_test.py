"""Explicit multi-area technique demonstration; not an automatic makeup assessment.

One paid generation, then local masking, diagnostics and annotated comparisons.
Run from the repository root with the installed package/virtual environment.
"""
import argparse
from dataclasses import dataclass
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from makeup_refine.config import get_api_key
from makeup_refine.imaging import load_image, composite, SRGB_BYTES
from makeup_refine.landmarks import MediaPipeLandmarks, LIPS
from makeup_refine.preflight import check_image, validate_masks
from makeup_refine.models import Change
from makeup_refine.providers import OpenAIProvider
from makeup_refine.quality import validate_candidate_geometry, region_metrics
from makeup_refine.report import data_url


@dataclass
class TechniqueTest:
    changes: list[Change]


GUIDES = {
    'eyeliner': 'Lift the outer tip slightly upward.',
    'eyeshadow': 'Blend outward and a little higher.',
    'lips': 'Outline the lips; neaten the corners.',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('photo', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output directory')
    original = load_image(args.photo)
    detector = MediaPipeLandmarks('models/face_landmarker.task')
    provider = OpenAIProvider(get_api_key(), 'gpt-4.1-mini', 'gpt-image-2')
    try:
        pre = check_image(original, detector)
        w, h = original.size
        masks = dict(pre.masks)
        # Limit lipstick edits to the contour: do not tint the whole lip.
        ring = Image.new('L', original.size)
        draw = ImageDraw.Draw(ring)
        contour = [(x*w,y*h) for x,y in [pre.points[i] for i in LIPS]]
        draw.line(contour+[contour[0]], fill=255, width=6, joint='curve')
        ring = ring.filter(ImageFilter.GaussianBlur(.8))
        masks['lips'] = Image.fromarray(np.minimum(np.asarray(ring),np.asarray(masks['lips'])))
        union = validate_masks(list(masks.values()))
        plan = TechniqueTest([
            Change(area='eyeliner',type='lift_outer_wing',severity='subtle',
                   instruction=GUIDES['eyeliner'], rationale='User-requested placement experiment, not detected makeup.'),
            Change(area='eyeshadow',type='blend_upward',severity='subtle',
                   instruction=GUIDES['eyeshadow'], rationale='User-requested placement experiment, not detected makeup.'),
            Change(area='lips',type='refine_edge',severity='subtle',
                   instruction=GUIDES['lips'], rationale='User-requested contour experiment; keep the center lip color.')])
        args.output.mkdir(parents=True,mode=0o700)
        original.save(args.output/'original.png')
        union.save(args.output/'mask.png')
        for area,mask in masks.items():
            mask.save(args.output/f'mask-{area}.png')
        # Exactly one edit call. No automatic retries or additional analysis.
        candidate = provider.edit(original,union,plan,0)
        candidate.save(args.output/'candidate.png')
        candidate_deviation = validate_candidate_geometry(candidate,original,pre.points,detector)
        # Replace contour pigment, instead of overlapping two different outlines.
        # Soft shadow is attenuated; edge feathering remains for all areas.
        weights={'eyeliner':1.0,'eyeshadow':0.5,'lips':1.0}
        alpha=np.maximum.reduce([np.asarray(mask,dtype=float)*weights[area] for area,mask in masks.items()])
        blend_mask=Image.fromarray(np.rint(alpha).astype(np.uint8))
        result=composite(original,candidate,blend_mask)
        final_deviation=validate_candidate_geometry(result,original,pre.points,detector)
        metrics=region_metrics(original,result,list(masks.values()))
        assert np.array_equal(np.asarray(original)[np.asarray(union)==0],np.asarray(result)[np.asarray(union)==0])
        result.save(args.output/'refined.png')
        report={'status':'technique_demo_requires_review','analysisPerformed':False,'imageEditCalls':1,
                'candidateLandmarkDeviation':candidate_deviation,'finalLandmarkDeviation':final_deviation,
                'outsideMasksIdentical':True,'presentationStrengths':weights,
                'regions':[{ 'number':i+1,'area':area,'intendedChange':plan.changes[i].instruction,
                             'bounds':mask.getbbox(),'measurements':metrics[i]}
                           for i,(area,mask) in enumerate(masks.items())]}
        (args.output/'positions.json').write_text(json.dumps(report,indent=2))
        render(original,result,masks,args.output)
        print(json.dumps(report))
    finally:
        provider.close();detector.close()


def render(original,result,masks,output):
    fontpath='/System/Library/Fonts/Helvetica.ttc'
    font=ImageFont.truetype(fontpath,24);small=ImageFont.truetype(fontpath,18)
    colors={'eyeliner':'#157eae','eyeshadow':'#aa4cc0','lips':'#cd5a32'}
    marked=original.copy();draw=ImageDraw.Draw(marked)
    # Separate eye sides so the central nose is not presented as an edit region.
    for number,(area,mask) in enumerate(masks.items(),1):
        halves=[(0,original.width)]
        if area!='lips':
            occupied=np.flatnonzero(np.any(np.asarray(mask)>0,axis=0))
            gap=int(np.argmax(np.diff(occupied)))
            middle=int((occupied[gap]+occupied[gap+1])//2)
            halves=[(0,middle),(middle,original.width)]
        for left,right in halves:
            bounds=mask.crop((left,0,right,original.height)).getbbox()
            if not bounds:continue
            x0,y0,x1,y1=bounds;x0+=left;x1+=left
            draw.rectangle((x0-3,y0-3,x1+3,y1+3),outline=colors[area],width=2)
            tx=x0-30 if left==0 else x1+6
            ty=y0-25 if area=='eyeshadow' else y1+5
            draw.text((tx,ty),str(number),font=font,fill=colors[area],stroke_width=1,stroke_fill='white')
    marked.save(output/'annotated.png',icc_profile=SRGB_BYTES)
    board=Image.new('RGB',(1380,1380),'#f8f5f2');d=ImageDraw.Draw(board)
    for idx,(label,photo) in enumerate([('Original',original),('Combined test',result),('Where to check',marked)]):
        x=idx*460
        d.text((x+12,12),label,font=font,fill='#322a2d')
        board.paste(photo.resize((444,592),Image.Resampling.LANCZOS),(x+8,50))
    for i,(area,mask) in enumerate(masks.items()):
        y=666+i*228
        d.text((12,y),f'{i+1}. '+{'eyeliner':'Outer-wing position','eyeshadow':'Shadow placement','lips':'Lipstick boundary'}[area],font=font,fill=colors[area])
        d.text((12,y+40),GUIDES[area],font=small,fill='#322a2d')
        b=mask.getbbox();box=(max(0,b[0]-24),max(0,b[1]-22),min(original.width,b[2]+24),min(original.height,b[3]+22))
        for j,(label,photo) in enumerate([('Before',original),('After',result)]):
            x=450+j*460
            d.text((x,y),label,font=small,fill='#65575d')
            crop=photo.crop(box);crop.thumbnail((438,190),Image.Resampling.LANCZOS)
            # Allow enlargement for small source regions, keeping aspect ratio equal.
            scale=min(438/crop.width,190/crop.height)
            crop=crop.resize((round(crop.width*scale),round(crop.height*scale)),Image.Resampling.LANCZOS)
            board.paste(crop,(x,y+30))
    board.save(output/'comparison.png',icc_profile=SRGB_BYTES)
    html=f'''<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Position technique test</title><body style="background:#f8f5f2;font:18px system-ui;padding:20px"><h1>One photo, three technique tests</h1><p>1. Eyeliner wing position · 2. Eyeshadow placement · 3. Lipstick outline.</p><p>This is an explicit demonstration, not an assessment that all three changes are needed. Boxes show edit regions. Inspect whether each change is visible, natural and helpful.</p><img style="width:100%;max-width:1380px" src="{data_url(board)}" alt="Original, combined technique test, annotated locations and before-after close-ups"></body></html>'''
    (output/'review.html').write_text(html)


if __name__=='__main__':
    main()
