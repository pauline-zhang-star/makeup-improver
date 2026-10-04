from io import BytesIO

import numpy as np
import pytest
from PIL import Image, ImageCms

from makeup_refine.imaging import SRGB_BYTES, SRGB_PROFILE, composite, load_image, to_srgb
from makeup_refine.models import SpikeError
from makeup_refine.pipeline import Pipeline
from test_pipeline import Detector, Editor, Vision


def test_converts_profile_before_stripping_metadata():
    original = Image.new('RGB', (32, 32), (180, 130, 95))
    lab_profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB'))
    lab = ImageCms.profileToProfile(original, SRGB_PROFILE, lab_profile, outputMode='LAB')
    lab.info['exif'] = b'private metadata'
    converted = to_srgb(lab)
    expected = ImageCms.profileToProfile(lab, lab_profile, SRGB_PROFILE, outputMode='RGB',
                                         renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
    assert np.array_equal(converted, expected)
    assert set(converted.info) == {'icc_profile'}
    assert converted.info['icc_profile'] == SRGB_BYTES


def test_loader_retains_only_standard_profile(tmp_path):
    path = tmp_path / 'photo.png'
    original = Image.new('RGB', (512, 512), (190, 145, 111))
    exif = Image.Exif()
    exif[270] = 'private camera description'
    original.save(path, icc_profile=SRGB_BYTES, exif=exif)
    loaded = load_image(path)
    assert loaded.info['icc_profile'] == SRGB_BYTES
    assert not loaded.getexif()
    assert set(loaded.info) == {'icc_profile'}
    assert np.array_equal(loaded, original)


def test_loader_accepts_heic_and_strips_camera_metadata(tmp_path):
    path = tmp_path / 'photo.heic'
    Image.new('RGB', (512, 512), (190, 145, 111)).save(path, format='HEIF')
    loaded = load_image(path)
    assert loaded.size == (512, 512)
    assert loaded.mode == 'RGB'
    assert set(loaded.info) == {'icc_profile'}


def test_invalid_profile_is_not_silently_dropped(tmp_path):
    path = tmp_path / 'bad-profile.png'
    Image.new('RGB', (512, 512)).save(path, icc_profile=b'not an ICC profile')
    with pytest.raises(SpikeError) as exc:
        load_image(path)
    assert exc.value.code == 'INVALID_COLOR_PROFILE'


def test_composite_embeds_matching_profile_and_preserves_pixels(tmp_path):
    original = to_srgb(Image.new('RGB', (512, 512), (180, 130, 95)))
    edited = to_srgb(Image.new('RGB', (512, 512), (180, 138, 97)))
    mask = Image.new('L', (512, 512))
    mask.paste(255, (100, 100, 120, 120))
    result = composite(original, edited, mask)
    buffer = BytesIO()
    result.save(buffer, format='PNG')
    buffer.seek(0)
    with Image.open(buffer) as decoded:
        assert decoded.info['icc_profile'] == original.info['icc_profile']
        outside = np.asarray(mask) == 0
        assert np.array_equal(np.asarray(decoded)[outside], np.asarray(original)[outside])


def test_single_attempt_budget_is_enforced():
    image = Image.fromarray(np.random.default_rng(10).integers(60, 190, (512, 512, 3), dtype=np.uint8))
    editor = Editor(fail=2)
    with pytest.raises(SpikeError, match='one attempt'):
        Pipeline(Vision(), editor, Detector(), max_edit_attempts=1).run(image)
    assert editor.calls == [0]
