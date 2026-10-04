"""Local evidence for an already registered final pair; never changes the pixels.

These diagnostic thresholds request attention, not proof of a makeup change.
Overlapping eye masks cannot identify which cosmetic caused a difference.
"""
import numpy as np
from .look_mask import direct_edit_mask
from .models import SpikeError


def build_comparison_evidence(original, enhanced, points, style, selected, mask_for=None):
    if original.size != enhanced.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Image dimensions changed.')
    before = np.asarray(original.convert('RGB'), dtype=np.float32)
    after = np.asarray(enhanced.convert('RGB'), dtype=np.float32)
    signed = after - before
    delta = np.abs(signed).mean(axis=2)
    # Central differences give edge-change evidence, not an eyeliner classifier.
    def edges(pixels):
        gray = .2126 * pixels[:, :, 0] + .7152 * pixels[:, :, 1] + .0722 * pixels[:, :, 2]
        gy, gx = np.gradient(gray)
        return np.hypot(gx, gy)
    edge_delta = np.abs(edges(after) - edges(before))
    w, h = original.size
    split = min(w - 1, max(1, round(points[1][0] * w)))
    records = []
    for item in selected:
        area = {'brows': 'eyebrows', 'foundation': 'complexion'}.get(item['region'], item['region'])
        support = np.asarray(mask_for([item]) if mask_for else
                             direct_edit_mask(original.size, points, style, [item])) > 0
        parts = [support]
        if area in {'eyebrows', 'eyeliner', 'eyeshadow', 'lashes', 'blush'}:
            left, right = support.copy(), support.copy()
            left[:, split:] = False
            right[:, :split] = False
            parts = [left, right]
        crops = []
        for part in parts:
            ys, xs = np.where(part)
            if xs.size:
                pad = max(8, round(max(xs.max()-xs.min(), ys.max()-ys.min()) * .2))
                crops.append([max(0, int(xs.min())-pad), max(0, int(ys.min())-pad),
                              min(w, int(xs.max())+pad+1), min(h, int(ys.max())+pad+1)])
        count = int(support.sum())
        mean = float(delta[support].mean()) if count else 0.
        fraction = float((delta[support] >= 3.).mean()) if count else 0.
        records.append({'techniqueId': item['technique_id'], 'area': area,
                        'supportPixels': count, 'meanPixelDelta': mean,
                        'changedFraction': fraction,
                        'meanSignedRGBDelta': signed[support].mean(axis=0).tolist() if count else [0., 0., 0.],
                        'meanEdgeDelta': float(edge_delta[support].mean()) if count else 0.,
                        'needsCloseReview': mean >= 2. and fraction >= .2,
                        'cropBoxes': crops})
    return {'version': 1, 'imageSize': list(original.size),
            'alignment': 'same coordinates of original and final registered composite; no additional warp',
            'thresholdsCalibrated': False, 'regions': records}


def unresolved_evidence(evidence, comparison):
    """Surface disagreement without inventing instructions or changing confidence."""
    by_area = {a.area: a for a in comparison.assessments}
    pending = []
    for area in sorted({r['area'] for r in evidence.get('regions', [])}):
        assessment = by_area[area]
        regions = [r for r in evidence['regions'] if r['area'] == area]
        if (assessment.change == 'uncertain' or
                (any(r['needsCloseReview'] for r in regions) and
                 (assessment.change != 'changed' or assessment.confidence < .8))):
            pending.append({'area': area, 'change': assessment.change,
                            'confidence': assessment.confidence,
                            'before': assessment.before, 'after': assessment.after,
                            'reason': 'Local pixel evidence and visual assessment need review; pixel differences alone do not establish a makeup change.'})
    return pending
