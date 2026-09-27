import numpy as np
import pytest
from PIL import Image, ImageDraw

from makeup_refine.landmarks import LIPS, INNER_LIPS
from makeup_refine.lip_blend import blend_full_lips, lip_regions, _dilate, _harmonic_blend
from makeup_refine.look_mask import lip_mask
from makeup_refine.models import SpikeError


def points(height=.055):
    p = np.full((478, 2), .5)
    p[33], p[263] = (.25, .3), (.75, .3)
    for index, angle in zip(LIPS, np.linspace(np.pi, 3 * np.pi, len(LIPS), endpoint=False)):
        p[index] = (.5 + .22 * np.cos(angle), .60 + height * np.sin(angle))
    for index, angle in zip(INNER_LIPS, np.linspace(np.pi, 3 * np.pi, len(INNER_LIPS), endpoint=False)):
        p[index] = (.5 + .18 * np.cos(angle), .60 + .008 * np.sin(angle))
    return p


def face(p, offset=0):
    image = Image.new('RGB', (240, 200), (150+offset, 110+offset, 100+offset))
    xy = p * image.size
    draw = ImageDraw.Draw(image)
    draw.polygon([tuple(xy[i]) for i in LIPS], fill=(150+offset, 65+offset, 80+offset))
    draw.polygon([tuple(xy[i]) for i in INNER_LIPS], fill=(70+offset, 38+offset, 42+offset))
    # Lip texture that must survive the boundary correction.
    draw.line((115, 125, 116, 128), fill=(175+offset, 95+offset, 110+offset))
    return image


def test_automatic_repair_keeps_fuller_generated_outline_and_removes_offset():
    before_points, after_points = points(), points(.07)
    original, candidate = face(before_points), face(after_points, offset=24)
    result, report = blend_full_lips(original, candidate, before_points, after_points,
                                     lip_mask(original.size, before_points))
    union, new_lips, opening, _, area_ratio = lip_regions(original.size, before_points, after_points)
    old_lips = lip_regions(original.size, before_points, before_points)[1]
    new_outline = new_lips & ~old_lips
    assert area_ratio > 1.15
    assert report['qualityPassed'] and report['detectedBoundaryArtifact']
    assert report['after']['boundaryGradientP95'] < report['before']['boundaryGradientP95'] * .5
    assert report['after']['generatedLipCoverage'] == 1
    # Overlined pixels stay lipstick-colored; no reversion to original skin.
    pixels = np.asarray(result)
    assert pixels[new_outline, 1].mean() < np.asarray(original)[new_outline, 1].mean() - 20
    support = _dilate(union, report['after']['marginPixels']) & ~opening
    assert np.array_equal(pixels[~support], np.asarray(original)[~support])
    assert np.array_equal(pixels[opening], np.asarray(original)[opening])
    # Match the offset-free candidate within the lip body, retaining texture.
    expected = np.asarray(face(after_points))
    assert np.abs(pixels[new_lips & ~opening].astype(float) - expected[new_lips & ~opening]).mean() < 3


def test_identical_input_never_manufactures_lip_edits():
    p = points()
    original = face(p)
    result, report = blend_full_lips(original, original, p, p, lip_mask(original.size, p))
    assert np.array_equal(result, original)
    assert not report['detectedBoundaryArtifact']


def test_excessive_shape_change_is_rejected_instead_of_reverting_to_old_lips():
    p, changed = points(), points(.13)
    with pytest.raises(SpikeError, match='beyond safe cosmetic'):
        blend_full_lips(face(p), face(changed), p, changed, lip_mask((240, 200), p))


def test_shifted_mouth_opening_is_rejected():
    p = points()
    changed = p.copy()
    changed[INNER_LIPS, 1] += .02
    with pytest.raises(SpikeError, match='beyond safe cosmetic'):
        blend_full_lips(face(p), face(changed), p, changed, lip_mask((240, 200), p))


def test_unconverged_solver_does_not_return_an_unchecked_image():
    p = points()
    union, _, opening, _, _ = lip_regions((240, 200), p, p)
    with pytest.raises(SpikeError, match='did not converge'):
        _harmonic_blend(face(p), face(points(.07)), _dilate(union, 8) & ~opening,
                        max_iterations=1, tolerance=1e-9)


def test_residual_skin_color_block_is_rejected_automatically():
    p, expanded = points(), points(.07)
    original, candidate = face(p), face(expanded)
    # Deliberate generator artifact immediately above the new lip, not pigment.
    ImageDraw.Draw(candidate).rectangle((85, 101, 155, 103), fill=(30, 180, 40))
    with pytest.raises(SpikeError, match='without a visible seam'):
        blend_full_lips(original, candidate, p, expanded, lip_mask(original.size, p))
