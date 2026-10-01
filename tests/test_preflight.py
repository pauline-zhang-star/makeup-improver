import json
import numpy as np
from PIL import Image
import pytest

from makeup_refine.check_cli import main
from makeup_refine.imaging import load_image
from makeup_refine.landmarks import INNER_LIPS, LIPS, LOWER_EYES, UPPER_EYES, make_mask, validate_face
from makeup_refine.models import SpikeError
from makeup_refine.report import write_report
from test_pipeline import Detector


def feature_points():
    points = Detector().detect(None)[0]
    for contour, cx in zip(UPPER_EYES, (.4, .6)):
        direction = 1 if contour[0] == 33 else -1
        for i, t in zip(contour, np.linspace(0, 1, len(contour))):
            points[i] = (cx + direction * (t - .5) * .12, .4 - .025 * np.sin(t * np.pi))
    for contour, cx in zip(LOWER_EYES, (.4, .6)):
        direction = 1 if contour[0] == 33 else -1
        for i, t in zip(contour, np.linspace(0, 1, len(contour))):
            points[i] = (cx + direction * (t - .5) * .12, .4 + .025 * np.sin(t * np.pi))
    for i, angle in zip(INNER_LIPS, np.linspace(0, 2 * np.pi, len(INNER_LIPS), endpoint=False)):
        points[i] = (.5 + .08 * np.cos(angle), .65 + .012 * np.sin(angle))
    return points


def test_lip_mask_excludes_teeth():
    mask = make_mask((512, 512), feature_points(), "lips")
    assert mask.getpixel((256, 333)) == 0
    assert mask.getpixel((256, 348)) > 0


@pytest.mark.parametrize("area", ["eyeliner", "eyeshadow"])
def test_eye_masks_exclude_eye_interiors(area):
    mask = make_mask((512, 512), feature_points(), area)
    for x in (205, 307):
        assert mask.getpixel((x, 205)) == 0
    assert np.count_nonzero(mask) > 0


@pytest.mark.parametrize("points", [[], [(.5, .5)], [float("nan")] * 478, [[.5]] * 478,
                                     [[float("nan"), .5]] * 478])
def test_malformed_landmarks_return_application_error(points):
    with pytest.raises(SpikeError) as error:
        validate_face([points])
    assert error.value.code == "NO_FACE"


def test_mpo_uses_primary_photo(tmp_path):
    path = tmp_path / "phone.jpeg"
    primary = Image.new("RGB", (512, 512), "red")
    primary.save(path, format="MPO", save_all=True,
                 append_images=[Image.new("RGB", (512, 512), "blue")])
    with Image.open(path) as source:
        assert source.format == "MPO" and source.n_frames == 2
    image = load_image(path)
    red, green, blue = image.getpixel((256, 256))
    assert red > 240 and green < 5 and blue < 5
    assert set(image.info) == {"icc_profile"}


def test_local_command_writes_review_without_credentials(tmp_path, monkeypatch, capsys):
    class LocalDetector(Detector):
        def __init__(self, model):
            pass
        def detect(self, image):
            return [feature_points()]
        def close(self):
            pass
    monkeypatch.setattr("makeup_refine.landmarks.MediaPipeLandmarks", LocalDetector)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = tmp_path / "model.task"
    model.touch()
    photo = tmp_path / "photo.png"
    Image.fromarray(np.random.default_rng(11).integers(60, 190, (512, 512, 3), dtype=np.uint8)).save(photo)
    output = tmp_path / "result"
    assert main([str(photo), "--output", str(output), "--landmark-model", str(model)]) == 0
    result = json.loads((output / "preflight.json").read_text())
    assert result["networkUsed"] is False and result["makeupAnalysis"] == "not_run"
    assert (output / "review.html").is_file()
    assert not (output / "refined.png").exists()
    assert output.stat().st_mode & 0o077 == 0
    # A rerun cannot overwrite the prior photo or its report.
    assert main([str(photo), "--output", str(output), "--landmark-model", str(model)]) == 1
    assert "OUTPUT_EXISTS" in capsys.readouterr().err


def test_missing_model_error_is_actionable(tmp_path, capsys):
    assert main(["--doctor", "--landmark-model", str(tmp_path / "missing.task")]) == 1
    assert json.loads(capsys.readouterr().err)["errorCode"] == "MODEL_NOT_FOUND"


def test_report_escapes_provider_text_and_stays_offline(tmp_path):
    image = Image.new("RGB", (512, 512), "gray")
    report = tmp_path / "review.html"
    write_report(report, image, masks={}, result=image,
                 changes=[{"area": "lips", "instruction": '<script>alert("bad")</script>'}])
    html = report.read_text()
    assert '<script>alert("bad")</script>' not in html
    assert "&lt;script&gt;" in html
    assert "connect-src 'none'" in html
    assert 'type="range"' in html
    assert "fetch(" not in html


def test_face_detail_screen_ignores_detailed_background():
    from makeup_refine.preflight import face_detail_metrics
    from PIL import ImageFilter
    image = Image.fromarray(np.random.default_rng(4).integers(0,255,(512,512,3),dtype=np.uint8))
    points = feature_points()
    assert not face_detail_metrics(image, points)['rejected']
    soft = image.filter(ImageFilter.GaussianBlur(10))
    image.paste(soft.crop((130,140,390,400)),(130,140))
    assert face_detail_metrics(image, points)['rejected']
