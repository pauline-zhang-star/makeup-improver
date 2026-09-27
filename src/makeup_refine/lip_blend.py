"""Automatic spatial lip blending with measured skin seams and texture retention.

Solve a harmonic RGB correction inside a landmark-derived mouth region. This
keeps the generated lip gradients (including a fuller outline) while matching
the surrounding original/base skin at the boundary. No image-specific points.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .imaging import composite
from .landmarks import LIPS, INNER_LIPS
from .models import SpikeError


def _polygon(size, points, indices):
    xy = np.asarray(points, dtype=float) * size
    result = Image.new('L', size, 0)
    ImageDraw.Draw(result).polygon([tuple(xy[i]) for i in indices], fill=255)
    return np.asarray(result) > 0


def _dilate(mask, radius):
    image = Image.fromarray(mask.astype(np.uint8) * 255)
    return np.asarray(image.filter(ImageFilter.MaxFilter(2 * radius + 1))) > 0


def lip_regions(size, reference_points, candidate_points):
    """All regions follow detected contours, including the candidate's overline."""
    reference = _polygon(size, reference_points, LIPS)
    candidate = _polygon(size, candidate_points, LIPS)
    opening = _polygon(size, reference_points, INNER_LIPS)
    xy = np.asarray(reference_points, dtype=float) * size
    width = float(np.linalg.norm(xy[61] - xy[291]))
    if width < 8 or reference.sum() < 10 or candidate.sum() < 10:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Could not locate the lip surface reliably.')
    area_ratio = float(candidate.sum() / reference.sum())
    mouth_delta = float(np.linalg.norm((np.asarray(candidate_points) -
                       np.asarray(reference_points))[INNER_LIPS], axis=1).max())
    if not .65 <= area_ratio <= 1.6 or mouth_delta > .007:
        raise SpikeError('QUALITY_CHECK_FAILED', 'The generated mouth changed beyond safe cosmetic blending.')
    return reference | candidate, candidate, opening, width, area_ratio


def _harmonic_blend(base, source, support, tolerance=.003, max_iterations=1800):
    """Poisson blending via a harmonic offset, using a small cropped RGB solve."""
    if support[0].any() or support[-1].any() or support[:, 0].any() or support[:, -1].any():
        raise SpikeError('QUALITY_CHECK_FAILED', 'Lip blending reached the image boundary.')
    ys, xs = np.where(support)
    if not len(xs):
        raise SpikeError('QUALITY_CHECK_FAILED', 'No editable lip surface was found.')
    x0, x1, y0, y1 = xs.min()-1, xs.max()+2, ys.min()-1, ys.max()+2
    destination = np.asarray(base, dtype=np.float64)[y0:y1, x0:x1]
    source_pixels = np.asarray(source, dtype=np.float64)[y0:y1, x0:x1]
    solve = support[y0:y1, x0:x1]
    offset = destination - source_pixels
    yy, xx = np.indices(solve.shape)
    red = solve & ((xx + yy) % 2 == 0)
    black = solve & ~red
    # Outside pixels are fixed Dirichlet values. Red/black SOR converges without
    # a new numerical dependency and preserves all source detail inside lips.
    for iteration in range(max_iterations):
        residual = 0.
        for parity in (red, black):
            average = (offset[:-2, 1:-1] + offset[2:, 1:-1] +
                       offset[1:-1, :-2] + offset[1:-1, 2:]) * .25
            delta = average - offset[1:-1, 1:-1]
            selected = parity[1:-1, 1:-1]
            if selected.any():
                residual = max(residual, float(np.abs(delta[selected]).max()))
                offset[1:-1, 1:-1][selected] += 1.7 * delta[selected]
        if residual < tolerance:
            break
    if residual >= tolerance:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Lip boundary correction did not converge.')
    result = np.asarray(base).copy()
    values = np.rint(source_pixels + offset).clip(0, 255).astype(np.uint8)
    result[y0:y1, x0:x1][solve] = values[solve]
    return Image.fromarray(result), {'iterations': iteration + 1, 'solverResidual': residual}


def _metrics(result, base, source, union, candidate, opening, width, support):
    pixels = np.asarray(result, dtype=float)
    original = np.asarray(base, dtype=float)
    generated = np.asarray(source, dtype=float)
    residual = pixels - original
    # Evaluate the same surrounding skin band for every attempt, excluding the
    # actual pigment edge. This penalizes colored patches without penalizing lips.
    band = _dilate(union, max(3, round(width * .16))) & ~_dilate(union, 2)
    patch = float(np.percentile(np.linalg.norm(residual[band], axis=1), 95))
    # A percentile alone can hide a small colored block. Check local chromatic
    # differences separately from brightness: natural mouth-corner shadows can
    # have large luminance differences and are handled by the boundary check.
    encoded = Image.fromarray(np.rint(residual + 128).clip(0, 255).astype(np.uint8))
    local_delta = np.asarray(encoded.filter(ImageFilter.GaussianBlur(1.5)), dtype=float) - 128
    chroma_delta = local_delta - local_delta.mean(axis=2, keepdims=True)
    patch_peak = float(np.linalg.norm(chroma_delta[band], axis=1).max())
    edge_errors, texture_errors, texture_energy = [], [], []
    surface = candidate & ~_dilate(opening, 1)
    opening_boundary = _dilate(opening, 3)
    for axis in (0, 1):
        gradient = np.diff(pixels, axis=axis)
        base_gradient = np.diff(original, axis=axis)
        source_gradient = np.diff(generated, axis=axis)
        if axis == 0:
            boundary = ((support[1:] != support[:-1]) &
                        ~opening_boundary[1:] & ~opening_boundary[:-1])
            interior = surface[1:] & surface[:-1]
        else:
            boundary = ((support[:, 1:] != support[:, :-1]) &
                        ~opening_boundary[:, 1:] & ~opening_boundary[:, :-1])
            interior = surface[:, 1:] & surface[:, :-1]
        edge_errors.extend(np.linalg.norm((gradient - base_gradient)[boundary], axis=1))
        texture_errors.extend(np.sum((gradient - source_gradient)[interior] ** 2, axis=1))
        texture_energy.extend(np.sum(source_gradient[interior] ** 2, axis=1))
    seam = float(np.percentile(edge_errors, 95)) if edge_errors else 0.
    texture = float(np.sqrt(np.mean(texture_errors) / max(1., np.mean(texture_energy)))) if texture_errors else 0.
    return {'skinPatchP95': patch, 'skinChromaLocalPeak': patch_peak,
            'boundaryGradientP95': seam,
            'lipGradientRelativeError': texture,
            'generatedLipCoverage': float(np.mean(support[candidate & ~opening]))}


def blend_full_lips(base, source, reference_points, candidate_points, old_lips):
    """Measure the old seam, solve several margins and accept a checked result.

    Unacceptable spatial edits are rejected, never silently replaced by the old
    lip contour. Returned diagnostics are suitable for automated regression runs.
    """
    if base.size != source.size or old_lips.size != base.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Lip blend dimensions changed.')
    union, candidate, opening, width, area_ratio = lip_regions(base.size, reference_points, candidate_points)
    old = composite(base, source, old_lips)
    old_support = np.asarray(old_lips) > 0
    before = _metrics(old, base, source, union, candidate, opening, width, old_support)
    attempts = []
    results = []
    for fraction in (.055, .09, .14):
        radius = max(3, round(width * fraction))
        support = _dilate(union, radius) & ~opening
        result, solver = _harmonic_blend(base, source, support)
        metrics = _metrics(result, base, source, union, candidate, opening, width, support)
        # Thresholds are engineering guards, not an aesthetic score. A large
        # remaining seam or lost lip detail must fail instead of being shipped.
        accepted = (metrics['boundaryGradientP95'] <= 12 and
                    metrics['skinPatchP95'] <= 20 and
                    metrics['skinChromaLocalPeak'] <= 36 and
                    metrics['lipGradientRelativeError'] <= .45 and
                    metrics['generatedLipCoverage'] == 1.)
        score = metrics['skinPatchP95'] + 2 * metrics['boundaryGradientP95']
        attempts.append({**metrics, **solver, 'marginPixels': radius,
                         'accepted': bool(accepted), 'score': score})
        results.append(result)
    eligible = [i for i, attempt in enumerate(attempts) if attempt['accepted']]
    if not eligible:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Automatic lip blending could not preserve the fuller outline without a visible seam.')
    best = min(eligible, key=lambda i: attempts[i]['score'])
    return results[best], {'method': 'adaptive_poisson', 'before': before,
                          'after': attempts[best], 'attempts': attempts,
                          'candidateLipAreaRatio': area_ratio,
                          'detectedBoundaryArtifact': before['boundaryGradientP95'] > 12,
                          'qualityPassed': True}
