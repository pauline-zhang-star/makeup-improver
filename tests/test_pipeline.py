import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError
from makeup_refine.imaging import composite, load_image, quality_precheck
from makeup_refine.models import Plan, SpikeError
from makeup_refine.pipeline import Pipeline
from makeup_refine.landmarks import LIPS, make_mask


def plan(changes=True):
    return Plan(analysis=[dict(area=a, detected="yes", confidence=.9, notes="Visible")
                          for a in ("eyeliner", "eyeshadow", "lips")], changes=[dict(
        area="lips", type="adjust_temperature", severity="subtle",
        instruction="Add a thin layer of a slightly cooler lip color.",
        rationale="Coordinates with the eye makeup.")] if changes else [])


@pytest.fixture
def image():
    return Image.fromarray(np.random.default_rng(10).integers(60, 190, (512, 512, 3), dtype=np.uint8))


class Detector:
    def detect(self, image):
        p = [(0.5, 0.5)] * 478
        p[1], p[2] = (.2, .2), (.8, .8)
        p[33], p[263] = (.35, .4), (.65, .4)
        for i, angle in zip(LIPS, np.linspace(0, 2 * np.pi, len(LIPS), endpoint=False)):
            p[i] = (.5 + .12 * np.cos(angle), .65 + .04 * np.sin(angle))
        return [p]


class Vision:
    calls = 0
    def __init__(self, changes=True):
        self.changes = changes
    def analyze_and_plan(self, image):
        self.calls += 1
        return plan(self.changes)


class Editor:
    def __init__(self, fail=0):
        self.calls, self.fail = [], fail
    def edit(self, image, mask, plan, attempt):
        self.calls.append(attempt)
        if attempt < self.fail:
            return image.copy()
        return Image.fromarray((np.asarray(image).astype(int) + 8).clip(0, 255).astype(np.uint8))


def test_pixel_preservation_and_annotations(image):
    result, mask, report = Pipeline(Vision(), Editor(), Detector()).run(image)
    outside = np.asarray(mask) == 0
    assert np.array_equal(np.asarray(image)[outside], np.asarray(result)[outside])
    assert report["status"] == "completed"
    assert report["phase1Validated"] is False
    assert report["quality"]["identityAndRealism"] == "requires_human_review"
    assert all(0 <= v <= 1 for p in report["changes"][0]["annotation"]["normalizedPoints"] for v in p)


def test_no_changes_never_calls_editor(image):
    editor = Editor()
    result, mask, report = Pipeline(Vision(False), editor, Detector()).run(image)
    assert result is mask is None
    assert report["status"] == "completed_no_changes"
    assert editor.calls == []


def test_retry_changes_attempt(image):
    editor = Editor(fail=1)
    _, _, report = Pipeline(Vision(), editor, Detector()).run(image)
    assert editor.calls == [0, 1]
    assert report["attempts"] == 2


def test_retry_is_bounded(image):
    editor = Editor(fail=2)
    with pytest.raises(SpikeError, match="after two attempts"):
        Pipeline(Vision(), editor, Detector()).run(image)
    assert editor.calls == [0, 1]


def test_dark_photo_never_calls_ai():
    vision, editor = Vision(), Editor()
    with pytest.raises(SpikeError) as error:
        Pipeline(vision, editor, Detector()).run(Image.new("RGB", (512, 512)))
    assert error.value.code == "IMAGE_TOO_DARK"
    assert vision.calls == 0 and editor.calls == []


@pytest.mark.parametrize("faces,code", [([], "NO_FACE"), ([[], []], "MULTIPLE_FACES")])
def test_face_rejection_before_ai(image, faces, code):
    class BadDetector:
        def detect(self, image):
            return faces
    vision = Vision()
    with pytest.raises(SpikeError) as error:
        Pipeline(vision, Editor(), BadDetector()).run(image)
    assert error.value.code == code
    assert vision.calls == 0


def test_rejects_dimension_drift(image):
    with pytest.raises(SpikeError):
        composite(image, image.resize((256, 256)), Image.new("L", image.size))


def test_uncertain_makeup_cannot_be_changed():
    data = plan().model_dump()
    data["analysis"][2]["detected"] = "uncertain"
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_disallows_unscoped_edits():
    data = plan().model_dump()
    data["changes"][0]["type"] = "enlarge_eyes"
    with pytest.raises(ValidationError):
        Plan.model_validate(data)


def test_normalizes_and_strips_metadata(tmp_path):
    path = tmp_path / "input.jpg"
    Image.new("RGB", (1600, 1200)).save(path)
    result = load_image(path)
    assert result.size == (1600, 1200)
    assert not result.getexif()


def test_bad_file(tmp_path):
    path = tmp_path / "bad.png"
    path.write_text("not an image")
    with pytest.raises(SpikeError):
        load_image(path)


def test_mask_is_localized(image):
    mask = make_mask(image.size, Detector().detect(image)[0], "lips")
    assert 0 < np.count_nonzero(mask) < 512 * 512 * .1
    assert np.asarray(mask)[0, 0] == 0
