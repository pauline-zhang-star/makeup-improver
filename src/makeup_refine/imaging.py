from pathlib import Path
from io import BytesIO
import warnings
import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError
from .models import SpikeError

Image.MAX_IMAGE_PIXELS = 20_000_000
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
SRGB_BYTES = SRGB_PROFILE.tobytes()


def to_srgb(image: Image.Image) -> Image.Image:
    """Preserve displayed color before stripping private metadata.

    Untagged inputs are assumed sRGB. ICC metadata is color interpretation,
    not private capture metadata; dropping it can change every displayed pixel.
    """
    profile = image.info.get("icc_profile")
    if profile:
        try:
            source_profile = ImageCms.ImageCmsProfile(BytesIO(profile))
            compatible = image if image.mode in {"RGB", "CMYK", "L", "LAB"} else image.convert("RGB")
            converted = ImageCms.profileToProfile(
                compatible, source_profile, SRGB_PROFILE, outputMode="RGB",
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
        except (ImageCms.PyCMSError, OSError, ValueError, TypeError) as exc:
            raise SpikeError("INVALID_COLOR_PROFILE", "The photo's color profile could not be read. Export it as sRGB and try again.") from exc
    else:
        converted = image.convert("RGB")
    clean = Image.fromarray(np.asarray(converted))
    clean.info["icc_profile"] = SRGB_BYTES
    return clean


def load_image(path: Path) -> Image.Image:
    if path.stat().st_size > 20 * 1024 * 1024:
        raise SpikeError("UNSUPPORTED_IMAGE", "Choose an image smaller than 20 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if source.format not in {"JPEG", "MPO", "PNG", "WEBP"}:
                    raise SpikeError("UNSUPPORTED_IMAGE", "Use a JPEG, PNG, or WebP image.")
                # Phone JPEGs may include a secondary HDR/gain-map image (MPO).
                # Only the primary photograph belongs in the refinement pipeline.
                source.seek(0)
                image = to_srgb(ImageOps.exif_transpose(source))
                image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise SpikeError("UNSUPPORTED_IMAGE", "Choose a valid image under 20 megapixels.") from exc
    if min(image.size) < 512:
        raise SpikeError("IMAGE_TOO_SMALL", "Choose a photo at least 512 pixels on each side.")
    image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    # Retain the standard color profile, never camera/GPS metadata.
    return image


def quality_precheck(image: Image.Image) -> None:
    gray = np.asarray(image.convert("L"), dtype=float)
    if gray.mean() < 35:
        raise SpikeError("IMAGE_TOO_DARK", "Face a light source and retake the photo.")
    if gray.mean() > 230:
        raise SpikeError("IMAGE_TOO_BRIGHT", "Reduce direct light and retake the photo.")
    lap = -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    if lap.var() < 12:
        raise SpikeError("IMAGE_BLURRY", "Hold the camera steady and focus on your face.")


def composite(original: Image.Image, edited: Image.Image, mask: Image.Image,
              blend_strength: float = 1.0) -> Image.Image:
    """Blend once in encoded sRGB: original + strength * mask * (candidate-original).

    A strength sweep changes only this coefficient, never regenerates an image.
    The convention is recorded explicitly so tuning is reproducible.
    """
    if not np.isfinite(blend_strength) or not 0 <= blend_strength <= 1:
        raise ValueError("blend_strength must be between 0 and 1")
    if edited.size != original.size or mask.size != original.size:
        raise SpikeError("QUALITY_CHECK_FAILED", "The edit changed the image dimensions.")
    if mask.mode != "L":
        raise SpikeError("QUALITY_CHECK_FAILED", "The blend mask must be grayscale.")
    before = np.asarray(to_srgb(original), dtype=np.float64)
    after = np.asarray(to_srgb(edited), dtype=np.float64)
    alpha = blend_strength * np.asarray(mask, dtype=np.float64)[..., None] / 255
    result = Image.fromarray(np.rint(before + alpha * (after - before)).clip(0, 255).astype(np.uint8))
    result.info["icc_profile"] = SRGB_BYTES
    return result
