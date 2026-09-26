"""Short, reproducible instructions and normalized location hints."""
import numpy as np
from .models import Change, SpikeError

GUIDES = {
    'lift_outer_wing': ('Lift the outer tip slightly upward.', '眼尾轻轻向上提。'),
    'balance_eyeliner': ('Even out the thickness at both outer tips.', '两边眼尾画得一样粗。'),
    'soften_edge': ('Blend the hard shadow edge until soft.', '把眼影边缘晕柔和。'),
    'blend_upward': ('Blend outward and a little higher.', '向外、向上晕开一点。'),
    'adjust_temperature': ('Use a lip tone that matches the eye makeup.', '唇色调得与眼妆更协调。'),
    'adjust_depth': ('Add one thin layer of the same lip color.', '原来的唇色再薄涂一层。'),
    'refine_edge': ('Outline the lips; neaten the corners.', '描清唇边，嘴角收干净。'),
}


def location_outlines(mask, area):
    pixels = np.asarray(mask)
    occupied = np.flatnonzero(np.any(pixels > 0, axis=0))
    if not occupied.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Cannot annotate an empty edit mask.')
    w, h = mask.size
    sections = [(0, w)]
    if area in {'eyeliner', 'eyeshadow'} and occupied.size > 1:
        gaps = np.diff(occupied)
        i = int(gaps.argmax())
        if gaps[i] > 2:
            split = int((occupied[i] + occupied[i + 1]) // 2)
            sections = [(0, split), (split, w)]
    annotations = []
    for left, right in sections:
        box = mask.crop((left, 0, right, h)).getbbox()
        if not box:
            continue
        x0, y0, x1, y1 = box
        x0 += left; x1 += left
        annotations.append({'type': 'outline', 'normalizedPoints': [
            [x0/w, y0/h], [x1/w, y0/h], [x1/w, y1/h], [x0/w, y1/h]]})
    return annotations


def guided_change(change: Change, mask, index: int):
    english, chinese = GUIDES[change.type]
    annotations = location_outlines(mask, change.area)
    return {'id': f'change_{index + 1}', **change.model_dump(),
            'detailInstruction': change.instruction, 'instruction': english,
            'instructionZh': chinese, 'annotation': annotations[0],
            'annotations': annotations}
