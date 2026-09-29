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


COMPLEXION_TEXTURE_MIN_RATIO = .75


def preserve_complexion_texture(original, candidate, skin_mask,
                                minimum_ratio=COMPLEXION_TEXTURE_MIN_RATIO):
    """Restore fine original skin detail when a foundation edit smooths it away.

    Only high-frequency detail inside the selected foundation mask is restored;
    the candidate's low-frequency tone and makeup remain unchanged. This keeps
    wrinkles and pores readable while allowing light coverage to soften their
    contrast.
    """
    if original.size != candidate.size or original.size != skin_mask.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Complexion texture dimensions changed.')
    source = np.asarray(original.convert('RGB'), dtype=np.float32)
    edited = np.asarray(candidate.convert('RGB'), dtype=np.float32)
    source_low = np.asarray(original.filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32)
    edited_low = np.asarray(candidate.filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32)
    source_detail = source - source_low
    edited_detail = edited - edited_low
    weight = np.asarray(skin_mask, dtype=np.float32)[..., None] / 255.
    # Technique masks carry their requested intensity, so a placement mask
    # may legitimately peak below 50% while still covering the region.
    support = weight[..., 0] > .05
    if not np.any(support):
        raise SpikeError('QUALITY_CHECK_FAILED', 'The foundation texture mask is empty.')
    source_energy = float(np.mean(np.abs(source_detail[support])))
    edited_energy = float(np.mean(np.abs(edited_detail[support])))
    target_energy = source_energy * minimum_ratio
    if source_energy <= 1e-6 or edited_energy >= target_energy:
        return candidate, {'textureRestorationApplied': False,
                           'textureEnergyBefore': source_energy,
                           'textureEnergyAfter': edited_energy,
                           'textureEnergyRatio': edited_energy / max(source_energy, 1e-6),
                           'minimumTextureEnergyRatio': minimum_ratio}
    restoration = min(1., max(0., (target_energy - edited_energy) /
                              max(source_energy - edited_energy, 1e-6)))
    restored = edited + weight * restoration * (source_detail - edited_detail)
    restored = np.rint(restored).clip(0, 255).astype(np.uint8)
    final = Image.fromarray(restored)
    final_low = np.asarray(final.filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float32)
    final_energy = float(np.mean(np.abs((restored - final_low)[support])))
    if final_energy < target_energy * .95:
        raise SpikeError('QUALITY_CHECK_FAILED',
                         'The foundation edit removed too much natural skin texture.',
                         {'textureEnergyBefore': source_energy,
                          'textureEnergyAfter': final_energy,
                          'textureEnergyRatio': final_energy / max(source_energy, 1e-6),
                          'minimumTextureEnergyRatio': minimum_ratio})
    return final, {'textureRestorationApplied': True,
                   'textureRestorationStrength': restoration,
                   'textureEnergyBefore': source_energy,
                   'textureEnergyAfter': final_energy,
                   'textureEnergyRatio': final_energy / max(source_energy, 1e-6),
                   'minimumTextureEnergyRatio': minimum_ratio}
