import numpy as np
import pytest
from PIL import Image

from makeup_refine.imaging import composite
from makeup_refine.look_alignment import ANCHORS, align_candidate
from makeup_refine.look_mask import makeup_mask, lip_mask, lip_pigment_mask
from makeup_refine.look_composite import composite_makeup, lip_geometry_compatible
from makeup_refine.models import SpikeError
from test_pipeline import Detector


class LandmarkSequence:
    def __init__(self, points):
        self.points = points

    def detect(self, image):
        return [self.points]


def test_affine_recomposition_is_aligned_before_masked_composite():
    original = Image.new('RGB', (788, 524), (110, 120, 130))
    reference = np.asarray(Detector().detect(original)[0], dtype=float)
    # Match the observed class of failure: the model zoomed and moved the face.
    found = reference * (1.2, 1.2) + (-.10, -.08)
    candidate = Image.new('RGB', original.size, (210, 80, 100))
    aligned, report = align_candidate(original, candidate, reference.tolist(),
                                      LandmarkSequence(found.tolist()))
    mask = makeup_mask(original.size, reference)
    result = composite(original, aligned, mask)
    assert report['affineCorrectionApplied'] is True
    assert report['rawMaxLandmarkDeviation'] > .012
    assert report['alignmentMaxResidual'] < 1e-10
    assert np.array_equal(np.asarray(result)[np.asarray(mask) == 0],
                          np.asarray(original)[np.asarray(mask) == 0])
    assert np.any(np.asarray(result)[np.asarray(mask) > 0] !=
                  np.asarray(original)[np.asarray(mask) > 0])


def test_non_affine_face_change_is_not_repaired():
    image = Image.new('RGB', (788, 524))
    reference = np.asarray(Detector().detect(image)[0], dtype=float)
    changed = reference.copy()
    changed[list(ANCHORS[:4]), 0] += [.08, -.08, .08, -.08]
    with pytest.raises(SpikeError, match='beyond safe alignment'):
        align_candidate(image, image.copy(), reference.tolist(),
                        LandmarkSequence(changed.tolist()))


def test_aligned_candidate_does_not_hide_output_size_change():
    image = Image.new('RGB', (788, 524))
    points = Detector().detect(image)[0]
    with pytest.raises(SpikeError, match='dimensions'):
        align_candidate(image, image.resize((800, 528)), points, Detector())


def test_lip_transfer_keeps_original_mouth_luminance_and_outside_pixels():
    original = Image.new('RGB', (512, 512), (130, 95, 92))
    candidate = Image.new('RGB', original.size, (25, 10, 12))
    points = Detector().detect(original)[0]
    allowed = makeup_mask(original.size, points)
    lips = lip_mask(original.size, points)
    result = composite_makeup(original, candidate, allowed, lips)
    support = np.asarray(lips) > 0
    original_y = np.asarray(original.convert('YCbCr'))[..., 0]
    result_y = np.asarray(result.convert('YCbCr'))[..., 0]
    assert abs(float(result_y[support].mean()) - float(original_y[support].mean())) < 2
    assert np.array_equal(np.asarray(result)[np.asarray(allowed) == 0],
                          np.asarray(original)[np.asarray(allowed) == 0])


def test_color_transfer_does_not_copy_candidate_lip_shape_or_solid_patch():
    original = Image.new('RGB', (512, 512), (140, 100, 100))
    points = Detector().detect(original)[0]
    lips = lip_mask(original.size, points)
    pigment = lip_pigment_mask(original.size, points)
    allowed = makeup_mask(original.size, points)
    candidate = Image.new('RGB', original.size, (140, 100, 100))
    candidate.paste((170, 30, 45), (180, 320, 335, 350))
    result = composite_makeup(original, candidate, allowed, lips,
                              pigment_lips=pigment)
    outside_pigment = (np.asarray(lips) > 0) & (np.asarray(pigment) == 0)
    assert np.array_equal(np.asarray(result)[outside_pigment],
                          np.asarray(original)[outside_pigment])


def test_spatial_lip_detail_requires_stable_mouth_landmarks():
    image = Image.new('RGB', (512, 512))
    reference = np.asarray(Detector().detect(image)[0], dtype=float)
    stable, maximum = lip_geometry_compatible(reference, image, LandmarkSequence(reference.tolist()))
    assert stable and maximum == 0
    changed = reference.copy()
    changed[14, 1] += .02
    stable, maximum = lip_geometry_compatible(reference, image, LandmarkSequence(changed.tolist()))
    assert not stable and maximum >= .02


def test_nose_bridge_is_editable_without_circular_nose_skin_holes():
    image = Image.new('RGB', (788, 524))
    points = list(Detector().detect(image)[0])
    for index, coordinate in {168: (.46, .41), 6: (.46, .44), 197: (.46, .47),
                              195: (.46, .50), 5: (.46, .52), 4: (.46, .55),
                              129: (.41, .56), 358: (.52, .56),
                              98: (.42, .60), 327: (.51, .60)}.items():
        points[index] = coordinate
    mask = np.asarray(makeup_mask(image.size, points))
    assert mask[round(.47 * image.height), round(.46 * image.width)] > 0
    assert mask[round(.60 * image.height), round(.42 * image.width)] > 0
    assert mask[round(.60 * image.height), round(.51 * image.width)] > 0
