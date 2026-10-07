from io import BytesIO
import numpy as np
from PIL import Image
from makeup_refine.landmark_cache import CachedLandmarks
from makeup_refine.cli import save_working_png
from makeup_refine.providers import png


class Detector:
    def __init__(self):
        self.calls = 0
        self.closed = False

    def detect(self, image):
        self.calls += 1
        return [[(float(image.getpixel((0, 0))[0]), .25)]]

    def close(self):
        self.closed = True


def test_cache_reuses_identical_pixels_but_rechecks_modified_images():
    detector = Detector()
    cache = CachedLandmarks(detector)
    image = Image.new('RGB', (20, 20), (10, 20, 30))
    first = cache.detect(image)
    first[0][0] = (99., 99.)
    assert cache.detect(image.copy()) == [[(10., .25)]]
    assert detector.calls == 1
    image.putpixel((0, 0), (11, 20, 30))
    assert cache.detect(image) == [[(11., .25)]]
    assert detector.calls == 2
    cache.close()
    assert not cache.cache and detector.closed


def test_cache_is_bounded_and_not_shared_across_requests():
    detector = Detector()
    cache = CachedLandmarks(detector, capacity=1)
    a = Image.new('RGB', (2, 2), (1, 2, 3))
    b = Image.new('RGB', (2, 2), (2, 2, 3))
    cache.detect(a); cache.detect(b); cache.detect(a)
    assert detector.calls == 3 and len(cache.cache) == 1
    other = CachedLandmarks(detector)
    other.detect(a)
    assert detector.calls == 4


def test_fast_public_and_api_png_encoding_is_lossless(tmp_path, monkeypatch):
    image = Image.fromarray(np.random.default_rng(9).integers(0, 256, (140, 120, 3), dtype=np.uint8))
    monkeypatch.setenv('MAKEUP_SKIP_REVIEW_HTML', '1')
    path = tmp_path / 'working.png'
    save_working_png(image, path)
    with Image.open(path) as saved:
        assert np.array_equal(np.asarray(saved), np.asarray(image))
    with Image.open(BytesIO(png(image))) as api_image:
        assert np.array_equal(np.asarray(api_image), np.asarray(image))
