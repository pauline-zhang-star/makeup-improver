"""Local checks shared by the diagnostic command and paid pipeline."""
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from .imaging import quality_precheck
from .interfaces import LandmarkProvider
from .landmarks import make_mask, validate_face
from .models import SpikeError


@dataclass
class Preflight:
    points: list[tuple[float, float]]
    masks: dict[str, Image.Image]
    face_bounds: tuple[int, int, int, int]


def face_detail_metrics(image, points):
    """Provisional local-detail screen; not a calibrated blur/occlusion classifier."""
    from .look_annotations import annotation_anchors
    boxes = annotation_anchors(points)['lips']['protected']
    entries = []
    for name, index, floor in [('left_eye', 2, 120.), ('right_eye', 3, 120.), ('lips', 5, 35.)]:
        box = tuple(round(v * image.size[j % 2]) for j, v in enumerate(boxes[index]))
        crop = image.crop(box)
        crop.thumbnail((160, 80), Image.Resampling.LANCZOS)
        gray = np.asarray(crop.convert('L').filter(ImageFilter.GaussianBlur(.6)), dtype=float)
        if min(gray.shape) < 3:
            score = 0.
        else:
            lap = -4*gray[1:-1,1:-1]+gray[:-2,1:-1]+gray[2:,1:-1]+gray[1:-1,:-2]+gray[1:-1,2:]
            score = float(lap.var())
        entries.append({'region': name, 'box': list(box), 'detailScore': score,
                        'experimentalMinimum': floor, 'insufficientDetail': score < floor})
    return {'method': 'local_detail_smoothed_laplacian_v1', 'thresholdsCalibrated': False,
            'regions': entries, 'rejected': sum(x['insufficientDetail'] for x in entries) >= 2}


def check_face(image: Image.Image, detector: LandmarkProvider):
    if image.mode != "RGB" or min(image.size) < 256 or max(image.size) > 3800:
        raise SpikeError("UNSUPPORTED_IMAGE", "Normalize the image with load_image before processing.")
    quality_precheck(image)
    points = validate_face(detector.detect(image))
    p = np.asarray(points)
    w, h = image.size
    box = (int(p[:, 0].min() * w), int(p[:, 1].min() * h),
           int(p[:, 0].max() * w), int(p[:, 1].max() * h))
    # A bright or detailed background cannot substitute for a usable face crop.
    quality_precheck(image.crop(box))
    details = face_detail_metrics(image, points)
    if details['rejected']:
        raise SpikeError('IMAGE_BLURRY',
            '眉眼或唇部细节不够清楚。请上传对焦清晰、光线均匀、头发不遮挡眉眼的照片，并尽量关闭美颜滤镜。',
            {'inputQuality': details, 'inputRejected': True, 'retryAction': 'upload_clearer_photo'})
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
