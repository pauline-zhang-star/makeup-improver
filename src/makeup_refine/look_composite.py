"""Keep the original mouth geometry while transferring generated lip pigment."""
import numpy as np
from PIL import Image, ImageFilter

from .imaging import composite
from .landmarks import INNER_LIPS, LIPS, validate_face
from .models import SpikeError


def composite_complexion_base(original, candidate, skin_mask, strength=.6):
    """Transfer only low-frequency facial tone; keep original skin texture."""
    if original.size != candidate.size or original.size != skin_mask.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Complexion composite dimensions changed.')
    if not 0 <= strength <= 1:
        raise ValueError('Complexion strength must be between zero and one.')
    original_pixels = np.asarray(original.convert('RGB'), dtype=np.float32)
    original_low = np.asarray(original.filter(ImageFilter.GaussianBlur(14)).convert('RGB'),
                              dtype=np.float32)
    candidate_low = np.asarray(candidate.filter(ImageFilter.GaussianBlur(14)).convert('RGB'),
                               dtype=np.float32)
    delta = np.clip(candidate_low - original_low, -25, 25)
    weight = np.asarray(skin_mask, dtype=np.float32)[..., None] / 255 * strength
    result = np.rint(original_pixels + weight * delta).clip(0, 255).astype(np.uint8)
    return Image.fromarray(result)


def lip_geometry_compatible(reference_points, aligned_candidate, detector):
    """Only copy spatial lipstick detail when the mouth opening stayed fixed."""
    reference = np.asarray(reference_points, dtype=float)
    found = np.asarray(validate_face(detector.detect(aligned_candidate)), dtype=float)
    if found.shape != reference.shape:
        raise SpikeError('QUALITY_CHECK_FAILED', 'The candidate changed landmark topology.')
    indices = LIPS + INNER_LIPS
    maximum = float(np.linalg.norm(found[indices] - reference[indices], axis=1).max())
    return maximum <= .007, maximum


def composite_makeup(original, candidate, allowed_mask, lips, spatial_lips=False,
                     pigment_lips=None):
    if original.size != candidate.size or original.size != allowed_mask.size or original.size != lips.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Makeup composite dimensions changed.')
    all_pixels = np.asarray(allowed_mask)
    lip_pixels = np.asarray(lips)
    if np.any((lip_pixels > 0) & (all_pixels == 0)):
        raise SpikeError('QUALITY_CHECK_FAILED', 'Lip region escaped the allowed makeup mask.')
    other_mask = Image.fromarray(np.where(lip_pixels > 0, 0, all_pixels).astype(np.uint8))
    base = composite(original, candidate, other_mask)
    if spatial_lips:
        return composite(base, candidate, lips)

    pigment_lips = pigment_lips or lips
    if pigment_lips.size != original.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Lip pigment mask dimensions changed.')
    pigment_pixels = np.minimum(np.asarray(pigment_lips), lip_pixels)
    pigment_lips = Image.fromarray(pigment_pixels)
    original_ycc = np.asarray(original.convert('YCbCr'), dtype=float)
    candidate_ycc = np.asarray(candidate.convert('YCbCr'), dtype=float)
    support = pigment_pixels > 80
    if not support.any():
        raise SpikeError('QUALITY_CHECK_FAILED', 'No visible lip region was found.')
    # A median chroma *shift* keeps the original lip's own shading and texture.
    # Never copy a candidate mouth opening or a solid median-color patch.
    chroma_shift = np.median(candidate_ycc[support, 1:3], axis=0) - np.median(
        original_ycc[support, 1:3], axis=0)
    chroma_shift = np.clip(chroma_shift, -28, 28)
    recolored = original_ycc.copy()
    recolored[..., 1:3] += .75 * chroma_shift
    channels = np.rint(recolored).clip(0, 255).astype(np.uint8)
    color_image = Image.merge('YCbCr', [Image.fromarray(channels[..., i]) for i in range(3)]).convert('RGB')
    return composite(base, color_image, pigment_lips)
