"""Conservative, local framing before the image-edit API sees a photo.

Only remove strong full-width letterboxing or enlarge a small detected face by
cropping the working photograph. Never rescale, invent, or composite pixels.
"""
import math
import numpy as np
from PIL import Image

from .landmarks import validate_face
from .models import SpikeError


def letterbox_box(image: Image.Image):
    """Find paired, nearly black screen bars with abrupt full-width edges."""
    width, height = image.size
    if height < 640:
        return None
    sample = np.asarray(image.resize((min(width, 160), height), Image.Resampling.BILINEAR))
    black_fraction = (sample.max(axis=2) < 24).mean(axis=1)
    dark_rows = black_fraction >= .90
    top = int(np.argmax(~dark_rows)) if not dark_rows.all() else height
    bottom = int(np.argmax(~dark_rows[::-1])) if not dark_rows.all() else height
    if not (.08 * height <= top <= .35 * height and
            .08 * height <= bottom <= .35 * height and
            height - top - bottom >= 512):
        return None
    transition = max(4, min(16, round(.012 * height)))
    if (np.median(black_fraction[top:top + transition]) > .25 or
            np.median(black_fraction[height - bottom - transition:height - bottom]) > .25):
        return None
    return (0, top, width, height - bottom)


def face_box(image: Image.Image, points):
    """Give hair, ears and neckline generous margins; crop only a small face."""
    width, height = image.size
    p = np.asarray(points, dtype=float)
    face_left, face_top = p.min(axis=0)
    face_right, face_bottom = p.max(axis=0)
    face_width = (face_right - face_left) * width
    face_height = (face_bottom - face_top) * height
    target_width = min(width, max(512, round(face_width / .38)))
    target_height = min(height, max(512, round(face_height / .40)))
    if target_width * target_height < 655360 and width * height >= 655360:
        factor = math.sqrt(655360 / (target_width * target_height))
        target_width = min(width, math.ceil(target_width * factor))
        target_height = min(height, math.ceil(target_height * factor))
        if target_width * target_height < 655360:
            target_height = min(height, math.ceil(655360 / target_width))
        if target_width * target_height < 655360:
            target_width = min(width, math.ceil(655360 / target_height))
    if target_width > .86 * width and target_height > .86 * height:
        return None
    # Avoid producing a canvas that the edit API would reject.
    if max(target_width / target_height, target_height / target_width) > 3:
        return None
    center_x = (face_left + face_right) * width / 2
    center_y = (face_top + face_bottom) * height / 2 + .04 * target_height
    left = max(0, min(width - target_width, round(center_x - target_width / 2)))
    top = max(0, min(height - target_height, round(center_y - target_height / 2)))
    return (left, top, left + target_width, top + target_height)


def frame_photo(image: Image.Image, detector):
    """Return a cropped working original and an auditable source-coordinate box."""
    source_size = image.size
    working = image
    offset_x = offset_y = 0
    reasons = []
    bars = letterbox_box(working)
    if bars:
        working = working.crop(bars)
        offset_x += bars[0]
        offset_y += bars[1]
        reasons.append('paired_black_letterbox')
    faces = []
    try:
        faces = detector.detect(working)
        points = validate_face(faces)
    except SpikeError as exc:
        # A single, finite detected face can be too small *before* framing.
        # Use those coordinates only to propose a crop; the normal pipeline
        # strictly revalidates the face and feature detail afterward.
        points = faces[0] if exc.code == 'FACE_TOO_SMALL' and len(faces) == 1 else None
    if points is not None:
        face = face_box(working, points)
        if face:
            working = working.crop(face)
            offset_x += face[0]
            offset_y += face[1]
            reasons.append('small_face_in_frame')
    if not reasons:
        return image, None
    working.info.update(image.info)
    x1, y1 = offset_x, offset_y
    details = {'method': 'conservative_local_framing_v1', 'sourceSize': list(source_size),
               'cropBox': [x1, y1, x1 + working.width, y1 + working.height],
               'workingSize': list(working.size), 'reasons': reasons,
               'sourcePreserved': True}
    return working, details
