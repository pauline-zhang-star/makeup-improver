"""Validate upload containers consistently across local and Vercel servers."""

from io import BytesIO

from PIL import Image

from . import heif_support  # registers the Pillow HEIF decoder


UPLOAD_SUFFIXES = {'JPEG': '.jpg', 'MPO': '.jpg', 'PNG': '.png', 'HEIF': '.heic'}


def validate_upload(raw: bytes) -> str:
    """Return the decoded format, accepting the primary photo in MPO/HEIF."""
    with Image.open(BytesIO(raw)) as image:
        image_format = image.format
        frames = getattr(image, 'n_frames', 1)
        if image_format not in UPLOAD_SUFFIXES or frames < 1 or (
                frames != 1 and image_format not in {'MPO', 'HEIF'}):
            raise ValueError('Use one JPEG, PNG, or HEIC photo.')
        if image.width * image.height > 20_000_000:
            raise ValueError('Photo dimensions are too large.')
        image.seek(0)
        image.verify()
    return image_format
