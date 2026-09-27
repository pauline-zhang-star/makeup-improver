"""Numerical guards for the spike, not calibrated perceptual judgments."""
from dataclasses import dataclass

import numpy as np

from .landmarks import validate_face
from .models import SpikeError


@dataclass(frozen=True)
class VisibilityThresholds:
    # Starting values for empirical calibration. Units are 8-bit sRGB values.
    min_mean_delta: float = 2.0
    max_mean_delta: float = 35.0
    pixel_delta: float = 3.0
    min_changed_fraction: float = 0.20


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
        raise SpikeError("QUALITY_CHECK_FAILED", "The candidate moved facial geometry; blending cannot repair it.")
    return maximum
