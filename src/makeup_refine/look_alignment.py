"""Correct whole-frame model recomposition before copying local makeup pixels."""
import numpy as np
from PIL import Image, ImageFilter

from .landmarks import validate_face
from .models import SpikeError
from .quality import protected_pixel_metrics


# Stable points around the eyes, brows, nose and mouth. A coherent affine
# movement can be corrected; a changed expression or face shape cannot.
ANCHORS = (33, 133, 263, 362, 70, 105, 336, 334,
           61, 291, 0, 17, 4, 1, 168, 10, 152)

# Fit one camera-like movement, excluding cosmetic brow and lip edges.
STABLE_ANCHORS = (168, 6, 197, 195, 1, 4, 33, 133, 263, 362,
                  10, 152, 234, 454, 127, 356)


def register_direct_candidate(original, candidate, reference_points, detector, editable_mask,
                              max_restored_border=.02):
    """Correct small global movement with no local face warp or opacity blend.

    Independent protected-image pixels must improve after registration. Only
    uncovered outer-border pixels may come from the original; never makeup.
    Experimental bounds remain stricter than the legacy affine repair below.
    """
    if candidate.size != original.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'The candidate changed the image dimensions.')
    reference = np.asarray(reference_points, dtype=float)
    found = np.asarray(validate_face(detector.detect(candidate)), dtype=float)
    if found.shape != reference.shape:
        raise SpikeError('QUALITY_CHECK_FAILED', 'The candidate changed landmark topology.')
    raw = float(np.linalg.norm(found - reference, axis=1).max())
    report = {'rawMaxLandmarkDeviation': raw, 'similarityCorrectionApplied': False,
              'cosmeticOpacity': 1.0}
    if raw <= .003:
        return candidate, report

    dimensions = np.asarray(original.size, dtype=float)
    source = reference[list(STABLE_ANCHORS)] * dimensions
    target = found[list(STABLE_ANCHORS)] * dimensions
    design = np.zeros((len(source) * 2, 4))
    design[0::2, 0], design[0::2, 1], design[0::2, 2] = source[:, 0], -source[:, 1], 1
    design[1::2, 0], design[1::2, 1], design[1::2, 3] = source[:, 1], source[:, 0], 1
    parameters, _, rank, _ = np.linalg.lstsq(design, target.reshape(-1), rcond=None)
    a, b, tx, ty = parameters
    scale = float(np.hypot(a, b))
    angle = float(np.degrees(np.arctan2(b, a)))
    linear = np.array(((a, -b), (b, a)))
    predicted = (reference * dimensions) @ linear.T + (tx, ty)
    residual = float(np.linalg.norm((predicted - found * dimensions) / dimensions, axis=1).max())
    center = dimensions / 2
    center_shift = float(np.linalg.norm((linear @ center + (tx, ty) - center) / dimensions))
    report.update(scale=scale, rotationDegrees=angle, translationPixels=[float(tx), float(ty)],
                  landmarkResidualAfterFit=residual)
    if (rank < 4 or not .95 <= scale <= 1.05 or abs(angle) > 2 or
            center_shift > .03 or residual > .012):
        raise SpikeError('QUALITY_CHECK_FAILED',
                         'The candidate cannot be corrected with a small uniform camera transform.', report)

    coefficients = (a, -b, tx, b, a, ty)
    valid = Image.new('L', original.size, 255).transform(
        original.size, Image.Transform.AFFINE, coefficients, Image.Resampling.NEAREST)
    # Bicubic interpolation samples beyond the nearest pixel. Reserve a two
    # pixel boundary so a valid nearest sample cannot leave black edge specks.
    missing = np.asarray(valid.filter(ImageFilter.MinFilter(5))) == 0
    report['restoredBorderFraction'] = float(missing.mean())
    if missing.mean() > max_restored_border or np.any(missing & (np.asarray(editable_mask) > 0)):
        raise SpikeError('QUALITY_CHECK_FAILED',
                         'Alignment would lose too much frame content or overlap makeup.', report)
    report['maxRestoredBorderFraction'] = max_restored_border
    aligned = candidate.transform(original.size, Image.Transform.AFFINE,
                                  coefficients, Image.Resampling.BICUBIC)
    # Exact replacement of only uncovered border pixels, no feather or fading.
    aligned.paste(original, (0, 0), Image.fromarray(missing.astype(np.uint8) * 255))
    aligned.info.update(candidate.info)
    # Compare the same genuinely observed pixels; restored borders cannot make
    # an otherwise bad transform appear to improve independent image evidence.
    common_mask = np.asarray(editable_mask).copy()
    common_mask[missing] = 255
    common_mask = Image.fromarray(common_mask)
    before = protected_pixel_metrics(original, candidate, common_mask)['protectedMeanPixelDelta']
    after = protected_pixel_metrics(original, aligned, common_mask)['protectedMeanPixelDelta']
    report.update(protectedMeanBeforeAlignment=before, protectedMeanAfterAlignment=after)
    if before <= 0 or after > before * .95:
        report['correctionSkippedReason'] = 'Protected image pixels did not improve by at least 5%.'
        return candidate, report
    report['similarityCorrectionApplied'] = True
    return aligned, report


def align_candidate(original, candidate, reference_points, detector):
    if candidate.size != original.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'The candidate changed the image dimensions.')
    reference = np.asarray(reference_points, dtype=float)
    found = np.asarray(validate_face(detector.detect(candidate)), dtype=float)
    if found.shape != reference.shape:
        raise SpikeError('QUALITY_CHECK_FAILED', 'The candidate changed landmark topology.')
    raw_deviation = float(np.linalg.norm(found - reference, axis=1).max())
    if raw_deviation <= .012:
        return candidate, {'rawMaxLandmarkDeviation': raw_deviation,
                           'affineCorrectionApplied': False}

    scale = np.asarray(original.size, dtype=float)
    source = reference[list(ANCHORS)] * scale
    target = found[list(ANCHORS)] * scale
    matrix, *_ = np.linalg.lstsq(np.c_[source, np.ones(len(source))], target, rcond=None)
    linear = matrix[:2, :].T
    singular_values = np.linalg.svd(linear, compute_uv=False)
    residual = np.linalg.norm((np.c_[source, np.ones(len(source))] @ matrix - target) / scale, axis=1)
    if (np.any(singular_values < .7) or np.any(singular_values > 1.4)
            or float(residual.max()) > .012):
        raise SpikeError('QUALITY_CHECK_FAILED', 'The candidate changed facial shape beyond safe alignment.')
    aligned = candidate.transform(original.size, Image.Transform.AFFINE,
                                  tuple(matrix.T.flatten()), Image.Resampling.BICUBIC)
    return aligned, {'rawMaxLandmarkDeviation': raw_deviation,
                     'affineCorrectionApplied': True,
                     'alignmentMaxResidual': float(residual.max())}
