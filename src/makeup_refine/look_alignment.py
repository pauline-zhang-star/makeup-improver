"""Correct whole-frame model recomposition before copying local makeup pixels."""
import numpy as np
from PIL import Image

from .landmarks import validate_face
from .models import SpikeError


# Stable points around the eyes, brows, nose and mouth. A coherent affine
# movement can be corrected; a changed expression or face shape cannot.
ANCHORS = (33, 133, 263, 362, 70, 105, 336, 334,
           61, 291, 0, 17, 4, 1, 168, 10, 152)


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
