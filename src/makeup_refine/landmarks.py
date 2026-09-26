import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from .models import SpikeError

# MediaPipe Face Mesh topology, in contour order.
LIPS = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291,
        375, 321, 405, 314, 17, 84, 181, 91, 146]
INNER_LIPS = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308,
              324, 318, 402, 317, 14, 87, 178, 88, 95]
UPPER_EYES = [[33, 246, 161, 160, 159, 158, 157, 173, 133],
              [263, 466, 388, 387, 386, 385, 384, 398, 362]]
LOWER_EYES = [[33, 7, 163, 144, 145, 153, 154, 155, 133],
              [263, 249, 390, 373, 374, 380, 381, 382, 362]]


class MediaPipeLandmarks:
    def __init__(self, model_path: str):
        import mediapipe as mp
        self.mp = mp
        self.detector = mp.tasks.vision.FaceLandmarker.create_from_options(
            mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=model_path,
                                                  delegate=mp.tasks.BaseOptions.Delegate.CPU),
                running_mode=mp.tasks.vision.RunningMode.IMAGE, num_faces=2,
                min_face_detection_confidence=0.7,
                min_face_presence_confidence=0.7))

    def detect(self, image):
        result = self.detector.detect(self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB, data=np.asarray(image)))
        return [[(p.x, p.y) for p in face] for face in result.face_landmarks]

    def close(self):
        self.detector.close()


def validate_face(faces):
    if not faces:
        raise SpikeError("NO_FACE", "Use a clear, front-facing selfie.")
    if len(faces) != 1:
        raise SpikeError("MULTIPLE_FACES", "Choose a photo with only you in it.")
    try:
        points = np.asarray(faces[0], dtype=float)
    except (ValueError, TypeError) as exc:
        raise SpikeError("NO_FACE", "Could not locate facial features reliably.") from exc
    if (points.ndim != 2 or points.shape[0] < 468 or points.shape[1] != 2
            or not np.isfinite(points).all()):
        raise SpikeError("NO_FACE", "Could not locate facial features reliably.")
    if np.ptp(points[:, 0]) * np.ptp(points[:, 1]) < 0.08:
        raise SpikeError("FACE_TOO_SMALL", "Move closer to the camera.")
    if np.any(points < 0.015) or np.any(points > 0.985):
        raise SpikeError("FEATURES_NOT_VISIBLE", "Keep your whole face in the frame.")
    return faces[0]


def make_mask(size, points, area):
    if area not in {"lips", "eyeliner", "eyeshadow"}:
        raise SpikeError("QUALITY_CHECK_FAILED", "Unsupported mask area.")
    w, h = size
    xy = [(x * w, y * h) for x, y in points]
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    across = np.subtract(xy[263], xy[33])
    eye_span = float(np.linalg.norm(across))
    if eye_span < 10:
        raise SpikeError("FEATURES_NOT_VISIBLE", "Could not locate the eyes reliably.")
    # Follow head roll instead of extending every mask toward image-top.
    across = across / eye_span
    upward = np.array([across[1], -across[0]])
    if area == "lips":
        draw.polygon([xy[i] for i in LIPS], fill=255)
        # Teeth and the inside of an open mouth must never receive lip pigment.
        draw.polygon([xy[i] for i in INNER_LIPS], fill=0)
    else:
        for contour, lower in zip(UPPER_EYES, LOWER_EYES):
            line = [xy[i] for i in contour]
            if area == "eyeliner":
                draw.line(line, fill=255, width=max(3, round(eye_span * 0.025)))
                outer = line[0]
                sign = -1 if contour[0] == 33 else 1
                tip = np.array(outer) + sign * across * eye_span * 0.07 + upward * eye_span * 0.04
                draw.line([outer, tuple(tip)], fill=255,
                          width=max(3, round(eye_span * 0.025)))
            else:
                draw.polygon(line + [tuple(np.array(p) + upward * eye_span * 0.10)
                                     for p in reversed(line)], fill=255)
            # Remove eye interiors, including any line stroke spilling below lashes.
            draw.polygon(line + [xy[i] for i in reversed(lower)], fill=0)
    # Feather inward only: no edit support is introduced outside the named region.
    softened = mask.filter(ImageFilter.GaussianBlur(1.5))
    return Image.fromarray(np.minimum(np.asarray(mask), np.asarray(softened)))
