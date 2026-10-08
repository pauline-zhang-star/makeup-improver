"""Offline anatomy/appearance matrix: no API, no private photo dependencies."""
import numpy as np
import pytest
from PIL import Image, ImageDraw
from makeup_refine.landmarks import INNER_LIPS, LIPS
from makeup_refine.look_mask import lip_pigment_mask, mouth_interior_mask
from makeup_refine.imaging import edge_safe_composite
from makeup_refine.look_prompts import comparison_prompt
from makeup_refine.fast_ai import comparison_contract


def landmarks(gap, angle):
    p = np.full((478, 2), .5)
    for ids, rx, ry in [(LIPS, .22, .10), (INNER_LIPS, .18, gap/2)]:
        for i, a in zip(ids, np.linspace(0, 2*np.pi, len(ids), endpoint=False)):
            p[i] = (.5+rx*np.cos(a), .5+ry*np.sin(a))
    p[61], p[291] = (.28, .5), (.72, .5)
    p[13], p[14] = (.5, .5-gap/2), (.5, .5+gap/2)
    p[33], p[263] = (.3, .25), (.7, .25)
    a = np.deg2rad(angle)
    return (p-.5) @ np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]]) + .5


@pytest.mark.parametrize('skin', [(75, 45, 35), (165, 115, 85), (220, 175, 150)])
@pytest.mark.parametrize('state,gap', [('closed', .008), ('slightly_parted', .025), ('open', .08), ('teeth', .08)])
@pytest.mark.parametrize('angle', [0, 18])
def test_lip_surface_coverage_and_oral_interior_are_independent(skin, state, gap, angle):
    size = (320, 320)
    p = landmarks(gap, angle)
    original = Image.new('RGB', size, skin)
    if state == 'teeth':
        ImageDraw.Draw(original).polygon([tuple(v*320) for v in p[INNER_LIPS]], fill=(240, 238, 230))
    candidate = Image.new('RGB', size, (175, 45, 70))
    mask = lip_pigment_mask(size, p)
    mouth = np.asarray(mouth_interior_mask(size, p)) > 0
    final, _ = edge_safe_composite(original, candidate, mask, pigment_mask=mask)
    before, after = np.asarray(original), np.asarray(final)
    if state == 'closed':
        assert not mouth.any()
        assert max(abs(a-b) for a,b in zip(final.getpixel((160, 160)), candidate.getpixel((160, 160)))) <= 1
    else:
        assert mouth.any()
        assert np.array_equal(after[mouth], before[mouth])
        assert mask.getpixel((160, 160)) == 0
    outside = np.asarray(mask) == 0
    assert np.array_equal(after[outside], before[outside])


def test_fast_and_standard_review_require_lip_seam_artifact_inspection():
    for prompt in (comparison_prompt(), comparison_contract()[0]):
        assert 'lip-seam gaps' in prompt and 'makeup_artifacts' in prompt
        assert 'real open-mouth cavity' in prompt
