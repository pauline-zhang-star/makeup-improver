"""Numerical guards for the spike, not calibrated perceptual judgments."""
from dataclasses import dataclass

import numpy as np

from .landmarks import validate_face, UPPER_EYES, LOWER_EYES
from .models import SpikeError


@dataclass(frozen=True)
class VisibilityThresholds:
    # Starting values for empirical calibration. Units are 8-bit sRGB values.
    min_mean_delta: float = 2.0
    max_mean_delta: float = 35.0
    pixel_delta: float = 3.0
    min_changed_fraction: float = 0.20


@dataclass(frozen=True)
class ProtectedPixelThresholds:
    """Provisional tolerance for provider-side variation outside the mask.

    Image editing providers can introduce small tone and texture differences
    around a permitted facial base edit. Geometry and the paired-image review
    remain the stronger identity and scene checks.
    """
    max_mean_delta: float = 6.0
    max_fraction_above8: float = 0.25


def region_metrics(original, result, masks, thresholds=VisibilityThresholds()):
    if original.size != result.size:
        raise SpikeError("QUALITY_CHECK_FAILED", "Image dimensions changed.")
    delta = np.abs(np.asarray(result, dtype=float) - np.asarray(original, dtype=float)).mean(axis=2)
    regions = []
    for mask in masks:
        if mask.size != original.size or mask.mode != "L":
            raise SpikeError("QUALITY_CHECK_FAILED", "Invalid region mask.")
        support = np.asarray(mask) > 0
        if not support.any():
            raise SpikeError("QUALITY_CHECK_FAILED", "Empty region mask.")
        mean = float(delta[support].mean())
        fraction = float(np.mean(delta[support] >= thresholds.pixel_delta))
        too_little = mean < thresholds.min_mean_delta or fraction < thresholds.min_changed_fraction
        too_much = mean > thresholds.max_mean_delta
        regions.append({"meanPixelDelta": mean, "changedFraction": fraction,
                        "tooLittleChange": too_little, "tooMuchChange": too_much,
                        "passesNumericBand": not (too_little or too_much)})
    return regions


def validate_candidate_geometry(candidate, original, points, detector):
    if candidate.size != original.size:
        raise SpikeError("QUALITY_CHECK_FAILED", "The candidate changed the image dimensions.")
    found = np.asarray(validate_face(detector.detect(candidate)))
    reference = np.asarray(points)
    if found.shape != reference.shape:
        raise SpikeError("QUALITY_CHECK_FAILED", "The candidate changed landmark topology.")
    maximum = float(np.linalg.norm(found - reference, axis=1).max())
    # Check every landmark in the final composite. Registration and a local
    # mask must not leave a displaced mouth/eye or a doubled feature.
    if maximum > 0.012:
        raise SpikeError("QUALITY_CHECK_FAILED",
                         f"The generated image moved facial geometry beyond the allowed limit ({maximum:.4f} > 0.0120).")
    return maximum


def facial_proportion_metrics(image, detector):
    """Return appearance ratios that a landmark-position check cannot catch."""
    points = np.asarray(validate_face(detector.detect(image)), dtype=float)
    eye_span = float(np.linalg.norm(points[263] - points[33]))
    if eye_span <= 1e-6:
        raise SpikeError('FEATURES_NOT_VISIBLE', 'Could not measure the eyes reliably.')
    eye_opening = []
    for upper, lower in zip(UPPER_EYES, LOWER_EYES):
        eye_opening.append(float(np.mean(points[lower, 1]) - np.mean(points[upper, 1])))
    return {
        'leftEyeOpeningRatio': eye_opening[0] / eye_span,
        'rightEyeOpeningRatio': eye_opening[1] / eye_span,
        'noseWidthRatio': float(np.linalg.norm(points[98] - points[327]) / eye_span),
        'mouthWidthRatio': float(np.linalg.norm(points[61] - points[291]) / eye_span),
    }


def validate_facial_proportions(candidate, original, detector, max_relative_change=.05):
    """Reject feature reshaping even when all landmarks move together."""
    before = facial_proportion_metrics(original, detector)
    after = facial_proportion_metrics(candidate, detector)
    changes = {key: float((after[key] - before[key]) / max(abs(before[key]), 1e-6))
               for key in before}
    largest = max(changes, key=lambda key: abs(changes[key]))
    report = {'facialProportionsBefore': before, 'facialProportionsAfter': after,
              'facialProportionRelativeChanges': changes,
              'maxFacialProportionChange': abs(changes[largest]),
              'maxFacialProportionChangeAllowed': max_relative_change}
    if report['maxFacialProportionChange'] > max_relative_change:
        raise SpikeError('QUALITY_CHECK_FAILED',
                         'The generated image changed facial feature proportions '
                         f"({largest} changed {changes[largest]:+.1%}; "
                         f"limit {max_relative_change:.1%}).", report)
    return report


def protected_pixel_metrics(original, candidate, editable_mask):
    """Measure changes without altering either image."""
    if original.size != candidate.size or editable_mask.size != original.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'The edit changed the image dimensions.')
    protected = np.asarray(editable_mask) == 0
    if not np.any(protected):
        raise SpikeError('QUALITY_CHECK_FAILED', 'The edit left no protected pixels to verify.')
    delta = np.abs(np.asarray(original, dtype=np.float32) -
                   np.asarray(candidate, dtype=np.float32)).mean(axis=2)[protected]
    return {'protectedMeanPixelDelta': float(delta.mean()),
            'protectedFractionAbove8': float(np.mean(delta > 8))}


def validate_protected_pixels(original, candidate, editable_mask,
                              thresholds=ProtectedPixelThresholds()):
    """Reject repainting outside the permitted techniques and facial base makeup.

    Thresholds are provisional and deliberately conservative. This is a gate,
    never a request to lighten or blend the returned image.
    """
    report = protected_pixel_metrics(original, candidate, editable_mask)
    if (report['protectedMeanPixelDelta'] > thresholds.max_mean_delta or
            report['protectedFractionAbove8'] > thresholds.max_fraction_above8):
        raise SpikeError('QUALITY_CHECK_FAILED',
                         'The generated image changed areas outside the selected makeup regions and permitted facial base makeup '
                         f"(mean delta {report['protectedMeanPixelDelta']:.2f} > {thresholds.max_mean_delta:.2f}, "
                         f"fraction above 8: {report['protectedFractionAbove8']:.3f} > "
                         f"{thresholds.max_fraction_above8:.3f}).", report)
    report['protectedPixelThresholds'] = {
        'maxMeanDelta': thresholds.max_mean_delta,
        'maxFractionAbove8': thresholds.max_fraction_above8,
    }
    return report
