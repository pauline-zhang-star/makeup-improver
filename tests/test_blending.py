import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from makeup_refine.imaging import composite, to_srgb
from makeup_refine.models import SpikeError
from makeup_refine.pipeline import Pipeline
from makeup_refine.quality import region_metrics
from makeup_refine.sweep import sweep
from test_pipeline import Detector, Editor, Vision


def test_strength_is_deterministic_and_preserves_outside_pixels():
    before = Image.new('RGB', (32, 32), (100, 120, 140))
    candidate = Image.new('RGB', (32, 32), (200, 200, 200))
    mask = Image.new('L', before.size)
    mask.paste(255, (8, 8, 24, 24))
    results = [composite(before, candidate, mask, s) for s in (0, .3, .5, .7, 1)]
    assert np.array_equal(results[0], before)
    assert results[1].getpixel((16, 16)) == (130, 144, 158)
    assert results[2].getpixel((16, 16)) == (150, 160, 170)
    assert results[4].getpixel((16, 16)) == candidate.getpixel((16, 16))
    for result in results:
        assert result.getpixel((0, 0)) == before.getpixel((0, 0))
    assert np.array_equal(results[2], composite(before, candidate, mask, .5))


def test_feather_and_strength_are_applied_once():
    before = Image.new('RGB', (8, 8), (100, 100, 100))
    candidate = Image.new('RGB', (8, 8), (200, 200, 200))
    mask = Image.new('L', before.size, 128)
    assert composite(before, candidate, mask, .5).getpixel((0, 0)) == (125, 125, 125)


@pytest.mark.parametrize('strength', [-.1, 1.1, float('nan'), float('inf')])
def test_rejects_invalid_strength(strength):
    with pytest.raises(ValueError):
        composite(Image.new('RGB', (8, 8)), Image.new('RGB', (8, 8)), Image.new('L', (8, 8)), strength)


def test_symmetric_visibility_band():
    before = Image.new('RGB', (32, 32), (100, 100, 100))
    mask = Image.new('L', before.size, 255)
    weak = region_metrics(before, Image.new('RGB', before.size, (101, 101, 101)), [mask])[0]
    strong = region_metrics(before, Image.new('RGB', before.size, (160, 160, 160)), [mask])[0]
    visible = region_metrics(before, Image.new('RGB', before.size, (110, 110, 110)), [mask])[0]
    assert weak['tooLittleChange'] and not weak['passesNumericBand']
    assert strong['tooMuchChange'] and not strong['passesNumericBand']
    assert visible['passesNumericBand']


def test_each_region_must_change():
    original = Image.new('RGB', (32, 32), (100, 100, 100))
    edited = original.copy()
    edited.paste((115, 115, 115), (0, 0, 16, 32))
    left = Image.new('L', (32, 32)); left.paste(255, (0, 0, 16, 32))
    right = Image.new('L', (32, 32)); right.paste(255, (16, 0, 32, 32))
    metrics = region_metrics(original, edited, [left, right])
    assert metrics[0]['passesNumericBand'] and metrics[1]['tooLittleChange']


def test_weak_blend_retains_candidate_without_regeneration():
    image = Image.fromarray(np.random.default_rng(10).integers(60, 190, (512, 512, 3), dtype=np.uint8))
    editor = Editor()
    saved = []
    pipeline = Pipeline(Vision(), editor, Detector(), blend_strength=.01,
                        on_candidate=lambda *args: saved.append(args))
    with pytest.raises(SpikeError) as error:
        pipeline.run(image)
    assert error.value.code == 'EDIT_TOO_WEAK'
    assert editor.calls == [0]
    assert len(saved) == 1


def test_strong_blend_does_not_trigger_another_paid_edit():
    class StrongEditor(Editor):
        def edit(self, image, mask, plan, attempt):
            self.calls.append(attempt)
            return Image.new('RGB', image.size, (255, 255, 255))
    image = Image.fromarray(np.random.default_rng(10).integers(60, 190, (512, 512, 3), dtype=np.uint8))
    editor = StrongEditor()
    with pytest.raises(SpikeError) as error:
        Pipeline(Vision(), editor, Detector(), blend_strength=.7).run(image)
    assert error.value.code == 'EDIT_TOO_STRONG'
    assert editor.calls == [0]


def test_candidate_drift_cannot_hide_behind_low_strength():
    class DriftingDetector(Detector):
        calls = 0
        def detect(self, image):
            self.calls += 1
            points = super().detect(image)
            if self.calls > 1:
                x, y = points[0][61]
                points[0][61] = (x + .04, y)
            return points
    image = Image.fromarray(np.random.default_rng(10).integers(60, 190, (512, 512, 3), dtype=np.uint8))
    saved = []
    with pytest.raises(SpikeError):
        Pipeline(Vision(), Editor(), DriftingDetector(), max_edit_attempts=1,
                 blend_strength=.1, on_candidate=lambda *args: saved.append(args)).run(image)
    assert saved == []


def test_offline_sweep_reuses_candidate_and_does_not_choose_for_user(tmp_path):
    trial = tmp_path / 'trial'; trial.mkdir()
    original = to_srgb(Image.new('RGB', (32, 32), (100, 100, 100)))
    original.save(trial / 'original.png')
    Image.new('RGB', original.size, (160, 160, 160)).save(trial / 'candidate.png')
    mask = Image.new('L', original.size); mask.paste(255, (8, 8, 24, 24)); mask.save(trial / 'mask.png')
    manifest = {'status':'geometry_checked_candidate', 'original':'original.png',
                'candidate':'candidate.png', 'mask':'mask.png',
                'regions':[{'area':'lips', 'mask':'mask.png'}], 'plan':{'changes':[]}}
    (trial / 'candidate.json').write_text(json.dumps(manifest))
    output = tmp_path / 'sweep'
    report = sweep(trial, output, detector=Detector())
    assert report['newGenerations'] == 0 and report['networkUsed'] is False
    assert report['selectedStrength'] is None
    assert [r['blendStrength'] for r in report['variants']] == [.3, .5, .7]
    assert [r['passesNumericBand'] for r in report['variants']] == [True, True, False]
    assert all(r['outsideMaskIdentical'] for r in report['variants'])
    assert all(r['geometry']['status'] == 'passed' for r in report['variants'])
    assert report['geometry'] == 'checked_before_and_after_blending'
    assert (output / 'index.html').is_file()


def test_old_blended_result_is_not_mistaken_for_raw_candidate(tmp_path):
    Image.new('RGB', (32, 32)).save(tmp_path / 'refined.png')
    with pytest.raises(SpikeError) as error:
        sweep(tmp_path, tmp_path / 'sweep')
    assert error.value.code == 'CANDIDATE_NOT_FOUND'
