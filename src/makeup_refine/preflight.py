"""Local checks shared by the diagnostic command and paid pipeline."""
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .imaging import quality_precheck
from .interfaces import LandmarkProvider
from .landmarks import make_mask, validate_face
from .models import SpikeError


@dataclass
class Preflight:
    points: list[tuple[float, float]]
    masks: dict[str, Image.Image]
    face_bounds: tuple[int, int, int, int]


def check_face(image: Image.Image, detector: LandmarkProvider):
    if image.mode != "RGB" or min(image.size) < 256 or max(image.size) > 1024:
        raise SpikeError("UNSUPPORTED_IMAGE", "Normalize the image with load_image before processing.")
    quality_precheck(image)
    points = validate_face(detector.detect(image))
    p = np.asarray(points)
    w, h = image.size
    box = (int(p[:, 0].min() * w), int(p[:, 1].min() * h),
           int(p[:, 0].max() * w), int(p[:, 1].max() * h))
    # A bright or detailed background cannot substitute for a usable face crop.
    quality_precheck(image.crop(box))
    return points, box


def check_image(image: Image.Image, detector: LandmarkProvider) -> Preflight:
    points, box = check_face(image, detector)
    masks = {area: make_mask(image.size, points, area)
             for area in ("eyeliner", "eyeshadow", "lips")}
    return Preflight(points, masks, box)


def validate_masks(masks: list[Image.Image]) -> Image.Image:
    for mask in masks:
        if not np.any(np.asarray(mask)):
            raise SpikeError("FEATURES_NOT_VISIBLE", "Could not build a reliable feature mask.")
    union = Image.fromarray(np.maximum.reduce([np.asarray(m) for m in masks]))
    w, h = union.size
    if np.count_nonzero(np.asarray(union)) / (w * h) > 0.20:
        raise SpikeError("QUALITY_CHECK_FAILED", "The proposed edit mask is too broad.")
    return union
