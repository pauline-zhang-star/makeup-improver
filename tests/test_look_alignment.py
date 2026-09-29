import numpy as np
import pytest
from PIL import Image

from makeup_refine.imaging import composite, prepare_edit_canvas
from makeup_refine.look_alignment import ANCHORS, align_candidate, register_direct_candidate, STABLE_ANCHORS
from makeup_refine.look_mask import makeup_mask
from makeup_refine.models import SpikeError
from test_pipeline import Detector


class LandmarkSequence:
    def __init__(self, points):
        self.points = points

    def detect(self, image):
        return [self.points]


def test_small_camera_shift_is_corrected_without_fading_makeup():
    original = Image.fromarray(np.random.default_rng(9).integers(30, 160, (512, 512, 3), dtype=np.uint8))
    reference = np.asarray(Detector().detect(original)[0])
    candidate = original.transform(original.size, Image.Transform.AFFINE,
                                   (1, 0, 0, 0, 1, -8), Image.Resampling.NEAREST)
    candidate.paste((220, 40, 90), (250, 308, 260, 318))
    mask = Image.new('L', original.size, 0)
    mask.paste(255, (250, 300, 260, 310))
    aligned, report = register_direct_candidate(original, candidate, reference,
        LandmarkSequence((reference + (0, 8/512)).tolist()), mask)
    assert report['similarityCorrectionApplied']
    assert abs(report['scale'] - 1) < 1e-10
    assert abs(report['rotationDegrees']) < 1e-10
    assert aligned.getpixel((255, 305)) == (220, 40, 90)
    assert report['cosmeticOpacity'] == 1
    assert np.allclose(np.asarray(aligned)[100:200], np.asarray(original)[100:200], atol=1)


def test_fractional_registration_does_not_leave_black_border_specks():
    original = Image.new('RGB', (856, 1200), 'white')
    original.paste((80, 100, 150), (180, 150, 650, 1050))
    reference = np.asarray(Detector().detect(original)[0])
    angle = np.radians(.0825)
    linear = 1.00083 * np.array(((np.cos(angle), -np.sin(angle)),
                               (np.sin(angle), np.cos(angle))))
    translation = np.array((2.2, -7.45))
    inverse = np.linalg.inv(linear)
    coeff = np.c_[inverse, -inverse @ translation].reshape(-1)
    candidate = original.transform(original.size, Image.Transform.AFFINE,
                                   coeff, Image.Resampling.BICUBIC, fillcolor='white')
    found = ((reference * original.size) @ linear.T + translation) / original.size
    aligned, report = register_direct_candidate(original, candidate, reference,
        LandmarkSequence(found.tolist()), Image.new('L', original.size))
    assert report['similarityCorrectionApplied']
    assert np.asarray(aligned)[:40].min() > 240


def test_local_face_deformation_is_not_hidden_by_similarity_fit():
    original = Image.new('RGB', (512, 512), (100, 100, 100))
    reference = np.asarray(Detector().detect(original)[0])
    found = reference.copy()
    found[33, 0] -= .07
    found[263, 0] += .07
    with pytest.raises(SpikeError, match='uniform camera transform'):
        register_direct_candidate(original, original.copy(), reference,
            LandmarkSequence(found.tolist()), Image.new('L', original.size))


def test_excessive_missing_frame_is_not_invented():
    original = Image.new('RGB', (512, 512), (100, 100, 100))
    reference = np.asarray(Detector().detect(original)[0])
    with pytest.raises(SpikeError, match='lose too much frame'):
        register_direct_candidate(original, original.copy(), reference,
            LandmarkSequence((reference + (0, .025)).tolist()), Image.new('L', original.size))


def test_valid_resolution_preserves_photo_pixels_inside_reversible_padding():
    original = Image.fromarray(np.random.default_rng(5).integers(0, 255, (1200, 856, 3), dtype=np.uint8))
    mask = Image.new('L', original.size, 255)
    canvas, canvas_mask, box = prepare_edit_canvas(original, mask)
    assert canvas.size == canvas_mask.size == (864, 1200)
    assert box == (4, 0, 860, 1200)
    assert np.array_equal(np.asarray(canvas.crop(box)), np.asarray(original))
    assert canvas_mask.getpixel((0, 500)) == 0
    assert canvas_mask.getpixel((4, 500)) == 255


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
