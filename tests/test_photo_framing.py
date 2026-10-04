import numpy as np
from PIL import Image

from makeup_refine.models import SpikeError
from makeup_refine.photo_framing import face_box, frame_photo, letterbox_box
from makeup_refine.cli import cap_working_image


def framed_photo():
    photo = Image.new('RGB', (1000, 1800), 'black')
    photo.paste(Image.new('RGB', (1000, 1200), '#a78674'), (0, 300))
    # Sparse viewer controls are allowed inside otherwise uniform bars.
    photo.paste('white', (30, 140, 70, 150))
    return photo


def test_paired_screenshot_bars_are_removed_without_resizing_pixels():
    image = framed_photo()
    assert letterbox_box(image) == (0, 300, 1000, 1500)

    class NoFace:
        def detect(self, _):
            raise SpikeError('NO_FACE', 'No face.')

    cropped, details = frame_photo(image, NoFace())
    assert cropped.size == (1000, 1200)
    assert cropped.getpixel((500, 0)) == image.getpixel((500, 300))
    assert details['cropBox'] == [0, 300, 1000, 1500]
    assert details['sourceSize'] == [1000, 1800]
    assert details['reasons'] == ['paired_black_letterbox']


def test_small_face_crop_keeps_generous_margins_and_close_face_is_untouched():
    image = Image.new('RGB', (1600, 1200), '#a78674')
    small_points = [(.45, .42), (.55, .58)]
    box = face_box(image, small_points)
    assert box is not None
    assert box[2] - box[0] >= 512 and box[3] - box[1] >= 512
    assert (box[2] - box[0]) * (box[3] - box[1]) >= 655360
    assert box[0] < .45 * image.width < .55 * image.width < box[2]
    assert box[1] < .42 * image.height < .58 * image.height < box[3]
    assert face_box(image, [(.25, .20), (.75, .80)]) is None


def test_too_small_but_reliable_landmarks_can_seed_crop_before_strict_recheck():
    image = Image.new('RGB', (1600, 1800), '#a78674')
    points = [(.45, .42), (.55, .58)] * 239

    class SmallFace:
        def detect(self, _):
            return [points]

    cropped, details = frame_photo(image, SmallFace())
    assert details['reasons'] == ['small_face_in_frame']
    assert cropped.width < image.width and cropped.height < image.height


def test_dark_portrait_background_is_not_mistaken_for_letterbox():
    image = Image.new('RGB', (1000, 1800), 'black')
    # A dark backdrop with a face-like central object has no full-width photo edge.
    array = np.asarray(image).copy()
    yy, xx = np.ogrid[:1800, :1000]
    array[((xx - 500) / 250) ** 2 + ((yy - 900) / 430) ** 2 < 1] = (150, 110, 95)
    assert letterbox_box(Image.fromarray(array)) is None


def test_public_working_size_cap_keeps_one_aligned_portrait_and_records_resize():
    image = Image.new('RGB', (2316, 3088), '#a78674')
    image.info['icc_profile'] = b'test-profile'
    working, details = cap_working_image(image, None, image.size, 1536)
    assert working.size == (1152, 1536)
    assert working.info['icc_profile'] == b'test-profile'
    assert details['sourceSize'] == [2316, 3088]
    assert details['cropBox'] == [0, 0, 2316, 3088]
    assert details['workingSize'] == [1152, 1536]
    assert details['reasons'] == ['public_generation_size_limit']
    assert details['resized'] is True and details['sourcePreserved'] is False
    unchanged, no_details = cap_working_image(working, None, working.size, 1536)
    assert unchanged is working and no_details is None
