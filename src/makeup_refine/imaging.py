from pathlib import Path
from io import BytesIO
import warnings
import math
import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError
from . import heif_support  # registers the Pillow HEIF decoder
from .models import SpikeError

Image.MAX_IMAGE_PIXELS = 20_000_000
SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
SRGB_BYTES = SRGB_PROFILE.tobytes()


def edit_canvas(image: Image.Image):
    """Pad to GPT Image 2's size constraints without stretching or cropping input."""
    w, h = image.size
    scale = max(1., math.sqrt(655360 / (w * h)))
    cw, ch = math.ceil(w * scale / 16) * 16, math.ceil(h * scale / 16) * 16
    cw, ch = max(cw, math.ceil(ch / 3 / 16) * 16), max(ch, math.ceil(cw / 3 / 16) * 16)
    if max(cw, ch) > 3840 or cw * ch > 8294400:
        raise SpikeError('UNSUPPORTED_IMAGE', 'Image canvas exceeds supported model dimensions.')
    left, top = (cw-w)//2, (ch-h)//2
    pixels = np.pad(np.asarray(image), ((top,ch-h-top),(left,cw-w-left),(0,0)), mode='edge')
    padded = Image.fromarray(pixels)
    padded.info['icc_profile'] = SRGB_BYTES
    return padded, (left, top, left+w, top+h)


def scaled_edit_canvas(image: Image.Image) -> Image.Image:
    """Meet GPT Image 2's size limits without inventing a border around a face."""
    w, h = image.size
    scale = max(1., math.sqrt(655360 / (w * h)))
    cw, ch = math.ceil(w * scale / 16) * 16, math.ceil(h * scale / 16) * 16
    while cw * ch < 655360:
        if cw / w <= ch / h:
            cw += 16
        else:
            ch += 16
    if max(cw, ch) > 3840 or max(cw / ch, ch / cw) > 3 or cw * ch > 8294400:
        raise SpikeError('UNSUPPORTED_IMAGE', 'Image canvas exceeds supported model dimensions.')
    result = image.resize((cw, ch), Image.Resampling.LANCZOS) if (cw, ch) != image.size else image.copy()
    result.info['icc_profile'] = SRGB_BYTES
    return result


def compatible_edit_size(image: Image.Image) -> tuple[int, int]:
    """Choose a valid GPT Image 2 output size without altering the input pixels."""
    w, h = image.size
    scale = max(1., math.sqrt(655360 / (w * h)))
    cw, ch = math.ceil(w * scale / 16) * 16, math.ceil(h * scale / 16) * 16
    while cw * ch < 655360:
        if cw / w <= ch / h:
            cw += 16
        else:
            ch += 16
    if max(cw, ch) > 3840 or max(cw / ch, ch / cw) > 3 or cw * ch > 8294400:
        raise SpikeError('UNSUPPORTED_IMAGE', 'Image canvas exceeds supported model dimensions.')
    return cw, ch


def prepare_edit_canvas(image, mask):
    """Use an identical input/output canvas without stretching the photograph.

    Preserve input pixels when already above the model's minimum area. Only
    sub-minimum inputs are uniformly enlarged; add a few protected edge pixels
    to reach multiples of 16. The returned box exactly reverses this padding.
    """
    if mask.size != image.size or mask.mode != 'L':
        raise SpikeError('QUALITY_CHECK_FAILED', 'A matching edit mask is required.')
    cw, ch = compatible_edit_size(image)
    w, h = image.size
    factor = max(1., math.sqrt(655360 / (w * h)))
    sw, sh = min(cw, round(w * factor)), min(ch, round(h * factor))
    photo = image if (sw, sh) == image.size else image.resize((sw, sh), Image.Resampling.LANCZOS)
    local_mask = mask if mask.size == photo.size else mask.resize(photo.size, Image.Resampling.NEAREST)
    left, top = (cw-sw)//2, (ch-sh)//2
    canvas = Image.fromarray(np.pad(np.asarray(photo),
        ((top, ch-sh-top), (left, cw-sw-left), (0, 0)), mode='edge'))
    canvas.info.update(image.info)
    canvas_mask = Image.new('L', canvas.size, 0)
    canvas_mask.paste(local_mask, (left, top))
    return canvas, canvas_mask, (left, top, left+sw, top+sh)


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
                if source.format not in {"JPEG", "MPO", "PNG", "WEBP", "HEIF"}:
                    raise SpikeError("UNSUPPORTED_IMAGE", "Use a JPEG, PNG, WebP, or HEIC image.")
                # Phone JPEGs may include a secondary HDR/gain-map image (MPO).
                # Only the primary photograph belongs in the refinement pipeline.
                source.seek(0)
                image = to_srgb(ImageOps.exif_transpose(source))
                image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise SpikeError("UNSUPPORTED_IMAGE", "Choose a valid image under 20 megapixels.") from exc
    if min(image.size) < 512:
        raise SpikeError("IMAGE_TOO_SMALL", "Choose a photo at least 512 pixels on each side.")
    # Keep the camera resolution when the model can accommodate it. A large
    # source is reduced only to satisfy the edit model's documented limits.
    w, h = image.size
    scale = min(1., 3800 / max(w, h), math.sqrt(8_000_000 / (w * h)))
    if scale < 1:
        image = image.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                             Image.Resampling.LANCZOS)
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


def edge_safe_composite(original: Image.Image, edited: Image.Image, mask: Image.Image,
                        correction_strength: float = .65, soft_mask=None,
                        hard_mask=None, soft_feather_pixels: float = 12,
                        outer_feather_mask=None, outer_feather_pixels: float = 8):
    """Keep protected pixels while matching low-frequency color at the seam.

    The generated makeup remains inside the supplied mask. A blurred local
    color correction removes provider exposure/white-balance shifts near the
    transition, while the original texture and all zero-alpha pixels remain
    untouched. This is deliberately a color/alpha operation, never a face warp.
    """
    if edited.size != original.size or mask.size != original.size or mask.mode != 'L':
        raise SpikeError('QUALITY_CHECK_FAILED', 'The edge-safe composite dimensions or mask are invalid.')
    for region_mask in (soft_mask, hard_mask, outer_feather_mask):
        if region_mask is not None and (region_mask.size != mask.size or region_mask.mode != 'L'):
            raise SpikeError('QUALITY_CHECK_FAILED', 'A regional composite mask is invalid.')
    if not 0 <= correction_strength <= 1:
        raise ValueError('correction_strength must be between zero and one')
    if not np.isfinite(soft_feather_pixels) or soft_feather_pixels <= 0:
        raise ValueError('soft_feather_pixels must be positive and finite')
    if not np.isfinite(outer_feather_pixels) or outer_feather_pixels <= 0:
        raise ValueError('outer_feather_pixels must be positive and finite')
    before = np.asarray(to_srgb(original), dtype=np.float32)
    after = np.asarray(to_srgb(edited), dtype=np.float32)
    alpha = np.asarray(mask, dtype=np.float32) / 255.
    support = alpha > 0
    if not np.any(support):
        raise SpikeError('QUALITY_CHECK_FAILED', 'The edit mask has no compositing support.')
    # Technique intensity controls the provider request; keep full pigment in
    # the interior. A binary support with a two-pixel seam, however, turns a
    # soft cheek edit into a visibly stamped oval. Give only explicitly named
    # diffuse regions a wider inward fade, never opening protected pixels.
    if soft_mask is None:
        support_image = Image.fromarray(np.uint8(support) * 255)
        smoothed = np.asarray(support_image.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32) / 255.
        alpha = np.where(support, smoothed, 0.)
        soft_support = np.zeros_like(support)
    else:
        soft_support = (np.asarray(soft_mask) > 0) & support
        hard_support = support & ~soft_support
        if hard_mask is not None:
            hard_support |= (np.asarray(hard_mask) > 0) & support
        hard_image = Image.fromarray(np.uint8(hard_support) * 255)
        hard_blur = np.asarray(hard_image.filter(ImageFilter.GaussianBlur(2)), dtype=np.float32) / 255.
        hard_alpha = np.where(hard_support, hard_blur, 0.)
        soft_image = Image.fromarray(np.uint8(soft_support) * 255)
        soft_blur = np.asarray(soft_image.filter(
            ImageFilter.GaussianBlur(soft_feather_pixels)), dtype=np.float32) / 255.
        # A blurred binary mask is ~0.5 at its boundary. Remap that value to
        # zero so the last editable pixel does not create another hard seam.
        soft_alpha = np.where(soft_support, np.clip(2 * soft_blur - 1, 0., 1.), 0.)
        alpha = np.maximum(hard_alpha, soft_alpha)
    outer_coverage = 0.
    if outer_feather_mask is not None:
        outer_support = (np.asarray(outer_feather_mask) > 0) & support
        outer_coverage = float(np.mean(outer_support))
        if np.any(outer_support):
            # Fill enclosed openings before blurring: taper the outside of an
            # eye edit without also erasing shadow next to the protected iris.
            inverted = Image.fromarray(np.uint8(~outer_support) * 255).copy()
            if not outer_support[0, 0]:
                ImageDraw.floodfill(inverted, (0, 0), 0)
            envelope = outer_support | (np.asarray(inverted) > 0)
            blurred = np.asarray(Image.fromarray(np.uint8(envelope) * 255).filter(
                ImageFilter.GaussianBlur(outer_feather_pixels)), dtype=np.float32) / 255.
            outer_alpha = np.clip(2 * blurred - 1, 0., 1.)
            alpha = np.where(outer_support, np.minimum(alpha, outer_alpha), alpha)
    radius = max(2, min(12, round(min(original.size) * .012)))
    base_low = np.asarray(Image.fromarray(np.uint8(before)).filter(
        ImageFilter.GaussianBlur(radius)), dtype=np.float32)
    edit_low = np.asarray(Image.fromarray(np.uint8(after)).filter(
        ImageFilter.GaussianBlur(radius)), dtype=np.float32)
    low_frequency_shift = np.clip(base_low - edit_low, -24., 24.)
    corrected = np.clip(after + correction_strength * low_frequency_shift, 0., 255.)
    result = np.rint(before + alpha[..., None] * (corrected - before)).clip(0, 255).astype(np.uint8)
    output = Image.fromarray(result)
    output.info['icc_profile'] = SRGB_BYTES
    return output, {
        'method': 'edge_safe_color_matched_composite',
        'correctionStrength': correction_strength,
        'blurRadiusPixels': radius,
        'editableCoverageFraction': float(np.mean(support)),
        'softRegionCoverageFraction': float(np.mean(soft_support)),
        'softFeatherPixels': soft_feather_pixels if soft_mask is not None else 0,
        'outerFeatherCoverageFraction': outer_coverage,
        'outerFeatherPixels': outer_feather_pixels if outer_feather_mask is not None else 0,
        'protectedPixelsRestoredExactly': True,
    }
