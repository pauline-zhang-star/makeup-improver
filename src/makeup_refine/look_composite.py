"""Keep the original mouth geometry while transferring generated lip pigment."""
import numpy as np
from PIL import Image, ImageFilter

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
