"""Numerical guards for the spike, not calibrated perceptual judgments."""
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

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


# Forehead and face-outline anchors, excluding eyelids, brows, nostrils and lips.
PROPORTION_ANCHORS = (10, 151, 127, 356, 234, 454, 152, 172, 397)
# Central lid pairs exclude both canthi, where eyeliner most affects localization.
APERTURE_PAIRS = (((160, 144), (159, 145), (158, 153)),
                  ((385, 380), (386, 374), (387, 373)))


def _pixel_metrics(points, axes=None):
    axes = [] if axes is None else axes
    openings = []
    for index, pairs in enumerate(APERTURE_PAIRS):
        upper = np.asarray([points[a] for a, _ in pairs])
        lower = np.asarray([points[b] for _, b in pairs])
        if len(axes) <= index:
            # Use the ORIGINAL central lid midline, not a candidate eyeliner wing.
            tangent = (upper[-1] + lower[-1]) - (upper[0] + lower[0])
            length = np.linalg.norm(tangent)
            normal = np.array([-tangent[1], tangent[0]]) / length if length > 1e-8 else np.array([0., 1.])
            if normal[1] < 0:
                normal = -normal
            axes.append(normal)
        openings.append(float(np.mean((lower - upper) @ axes[index])))
    return {'leftEyeOpeningPixels': openings[0], 'rightEyeOpeningPixels': openings[1],
            'noseWidthPixels': float(np.linalg.norm(points[98] - points[327])),
            'mouthWidthPixels': float(np.linalg.norm(points[61] - points[291]))}, axes


def facial_proportion_metrics(image, detector):
    points = np.asarray(validate_face(detector.detect(image)), dtype=float) * image.size
    return _pixel_metrics(points)[0]


def paired_facial_metrics(original, candidate, detector):
    if original.size != candidate.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Image dimensions changed.')
    before = np.asarray(validate_face(detector.detect(original)), dtype=float) * original.size
    after = np.asarray(validate_face(detector.detect(candidate)), dtype=float) * original.size
    source, target = after[list(PROPORTION_ANCHORS)], before[list(PROPORTION_ANCHORS)]
    # One global similarity fit. No per-feature warping and no modified image pixels.
    design = np.zeros((len(source) * 2, 4))
    design[0::2, 0], design[0::2, 1], design[0::2, 2] = source[:, 0], -source[:, 1], 1
    design[1::2, 0], design[1::2, 1], design[1::2, 3] = source[:, 1], source[:, 0], 1
    if np.array_equal(source, target):
        a, b, tx, ty = 1., 0., 0., 0.
    else:
        params, _, rank, _ = np.linalg.lstsq(design, target.ravel(), rcond=None)
        if rank < 4:
            raise SpikeError('QUALITY_CHECK_FAILED', 'Insufficient stable anchors; geometry needs review.')
        a, b, tx, ty = params
    linear = np.array([[a, -b], [b, a]])
    aligned = after @ linear.T + (tx, ty)
    residual = float(np.max(np.linalg.norm(aligned[list(PROPORTION_ANCHORS)] - target, axis=1)))
    scale = float(np.hypot(a, b))
    angle = float(np.degrees(np.arctan2(b, a)))
    audit = {'method': 'stable_outline_similarity_pixel_measurement_v2', 'units': 'original_image_pixels',
             'anchorIndices': list(PROPORTION_ANCHORS), 'scale': scale, 'rotationDegrees': angle,
             'translationPixels': [float(tx), float(ty)], 'maxAnchorResidualPixels': residual,
             'normalizationByEyeSpan': False, 'independentEyeSegmentation': False,
             'landmarkDetectionMayShiftWithMakeup': True}
    center = np.asarray(original.size) / 2
    center_shift = float(np.linalg.norm((linear @ center + (tx, ty) - center) / original.size))
    audit['centerShiftFraction'] = center_shift
    if not .95 <= scale <= 1.05 or abs(angle) > 2 or center_shift > .03 or residual > .01 * min(original.size):
        raise SpikeError('QUALITY_CHECK_FAILED', 'Stable-anchor alignment is uncertain; geometry needs review.',
                         {'measurementAlignment': audit})
    first, axes = _pixel_metrics(before)
    second, _ = _pixel_metrics(aligned, axes)
    # If identical local pixels surround both detected positions, a detector shift
    # is not evidence of edited anatomy. Check before any mathematical alignment.
    groups = {'noseWidthPixels': (98, 327), 'mouthWidthPixels': (61, 291),
              'leftEyeOpeningPixels': tuple(i for pair in APERTURE_PAIRS[0] for i in pair),
              'rightEyeOpeningPixels': tuple(i for pair in APERTURE_PAIRS[1] for i in pair)}
    original_pixels, candidate_pixels = np.asarray(original), np.asarray(candidate)
    audit['localPixelEvidence'] = {}
    audit['rawMeasuredAfterPixels'] = dict(second)
    for key, indices in groups.items():
        support = np.concatenate([before[list(indices)], after[list(indices)]])
        low = np.maximum(0, np.floor(support.min(axis=0) - 8)).astype(int)
        high = np.minimum(original.size, np.ceil(support.max(axis=0) + 8)).astype(int)
        x0, y0 = low; x1, y1 = high
        unchanged = (x1 > x0 and y1 > y0 and np.array_equal(
            original_pixels[y0:y1, x0:x1], candidate_pixels[y0:y1, x0:x1]))
        audit['localPixelEvidence'][key] = {'box': [int(x0), int(y0), int(x1), int(y1)],
                                          'exactlyUnchanged': bool(unchanged)}
        if unchanged:
            second[key] = first[key]
    audit['eyeNormalVectors'] = [axis.tolist() for axis in axes]
    audit['measurementPointsBefore'] = {str(i): before[i].tolist() for i in
        sorted({98, 327, 61, 291} | {i for eye in APERTURE_PAIRS for pair in eye for i in pair})}
    audit['measurementPointsAfter'] = {str(i): aligned[i].tolist() for i in
        sorted({98, 327, 61, 291} | {i for eye in APERTURE_PAIRS for pair in eye for i in pair})}
    return first, second, audit


def eye_aperture_pixel_evidence(original, candidate, original_landmarks):
    """Check visible eye interiors and their lid-edge pixels independently of landmarks."""
    if original.size != candidate.size:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Image dimensions changed.')
    points = np.asarray(original_landmarks, dtype=float)
    if points.ndim != 2 or points.shape[0] < 468 or points.shape[1] != 2:
        raise SpikeError('QUALITY_CHECK_FAILED', 'Original eye landmarks are unavailable.')
    xy = points * original.size
    before, after = np.asarray(original), np.asarray(candidate)
    evidence = {}
    for key, upper, lower in zip(('leftEyeOpeningPixels', 'rightEyeOpeningPixels'),
                                 UPPER_EYES, LOWER_EYES):
        aperture = Image.new('L', original.size, 0)
        ImageDraw.Draw(aperture).polygon(
            [tuple(xy[i]) for i in upper] +
            [tuple(xy[i]) for i in reversed(lower)], fill=255)
        # The edit mask already protects a wider strip. These two pixels cover
        # the observed lid edge without reaching the permitted eyeshadow.
        protected = np.asarray(aperture.filter(ImageFilter.MaxFilter(5))) > 0
        checked = int(np.count_nonzero(protected))
        changed = np.any(before[protected] != after[protected], axis=1)
        evidence[key] = {'exactlyUnchanged': bool(checked >= 10 and not np.any(changed)),
                         'checkedPixels': checked,
                         'changedPixels': int(np.count_nonzero(changed))}
    return evidence


EYE_OPENING_RELATIVE_LIMIT = .06
# A named look may use a more visible eyelid/liner treatment. This only
# permits a small cosmetic increase in the measured aperture; the directional
# rule below still forbids making either eye look smaller.
STYLED_EYE_OPENING_RELATIVE_LIMIT = .08
EYE_OPENING_MIN_RELATIVE_CHANGE = 0.0
MOUTH_WIDTH_REVIEW_RELATIVE_LIMIT = .08


def validate_facial_proportions(candidate, original, detector, max_relative_change=.05,
                                style=None, original_landmarks=None):
    """Reject feature reshaping while allowing small cosmetic eye-opening effects.

    Eyeliner and double-eyelid makeup can change the measured eyelid opening a
    little without moving the eye or changing facial anatomy. Auto keeps the
    aperture increase to 6%; a named style may use up to 8% for a more visible
    cosmetic treatment. A measured decrease is accepted only when every pixel
    in the original visible eye aperture and its lid edge is unchanged; this
    distinguishes detector drift from a changed eye. Nose width remains
    at the supplied (normally 5%) limit in both modes. Mouth width changes
    beyond 8% require review because lip liner can alter the measured outline.
    """
    style_value = getattr(style, 'value', style)
    styled = style_value not in (None, 'Auto')
    eye_opening_limit = (STYLED_EYE_OPENING_RELATIVE_LIMIT if styled
                         else EYE_OPENING_RELATIVE_LIMIT)
    before, after, measurement_alignment = paired_facial_metrics(original, candidate, detector)
    changes = {key: (0.0 if abs(after[key] - before[key]) < 1e-7 else
                    float((after[key] - before[key]) / max(abs(before[key]), 1e-6)))
               for key in before}
    limits = {key: (EYE_OPENING_RELATIVE_LIMIT if key in {
                       'leftEyeOpeningPixels', 'rightEyeOpeningPixels'}
                    else max_relative_change)
              for key in changes if key != 'mouthWidthPixels'}
    for key in ('leftEyeOpeningPixels', 'rightEyeOpeningPixels'):
        limits[key] = eye_opening_limit
    eye_opening_keys = {'leftEyeOpeningPixels', 'rightEyeOpeningPixels'}
    aperture_evidence = (eye_aperture_pixel_evidence(original, candidate, original_landmarks)
                         if original_landmarks is not None else {})
    landmark_shift_only = sorted(key for key in eye_opening_keys
                                 if changes[key] < 0 and
                                 aperture_evidence.get(key, {}).get('exactlyUnchanged'))
    magnitude_violations = [key for key, change in changes.items()
                            if key in limits and abs(change) > limits[key]
                            and key not in landmark_shift_only]
    # Cosmetic eyeliner or eyelid makeup may leave the aperture unchanged or
    # make it look slightly more open, but it must never make either eye look
    # more closed. This directional rule is separate from the magnitude cap.
    eye_opening_decrease_violations = [
        key for key in eye_opening_keys
        if changes[key] < EYE_OPENING_MIN_RELATIVE_CHANGE and key not in landmark_shift_only
    ]
    violations = sorted(set(magnitude_violations + eye_opening_decrease_violations))
    mouth_change = changes['mouthWidthPixels']
    mouth_review = abs(mouth_change) > MOUTH_WIDTH_REVIEW_RELATIVE_LIMIT + 1e-9
    reportable = violations or (set(limits) - set(landmark_shift_only))
    reported = max(reportable,
                   key=lambda key: abs(changes[key]) / max(limits[key], 1e-6))
    report = {'measurementAlignment': measurement_alignment,
              'measurementUnits': 'pixels',
              'mouthWidthReview': {
                  'status': 'needs_review' if mouth_review else 'within_limit',
                  'relativeChange': mouth_change,
                  'relativeLimit': MOUTH_WIDTH_REVIEW_RELATIVE_LIMIT,
                  'reason': ('Lipstick or liner can change the measured outline; '
                             'a change beyond 8% needs visual review, not automatic rejection.')
                            if mouth_review else None,
              },
              'facialProportionsBefore': before, 'facialProportionsAfter': after,
              'facialProportionRelativeChanges': changes,
              'maxFacialProportionChange': abs(changes[reported]),
              'maxFacialProportionChangeAllowed': limits[reported],
              'facialProportionLimits': limits,
              'facialProportionMode': 'styled' if styled else 'auto',
              'eyeOpeningDirection': 'non_decreasing',
              'eyeOpeningDecreaseViolations': eye_opening_decrease_violations,
              'eyeAperturePixelEvidence': aperture_evidence,
              'eyeOpeningLandmarkShiftOnly': landmark_shift_only}
    if violations:
        pixel_change = abs(after[reported] - before[reported])
        report['measurementNeedsReview'] = pixel_change <= 1.0
        if reported in eye_opening_decrease_violations:
            message = ('The generated image reduced eye opening '
                       f"({reported} changed {changes[reported]:+.1%}; "
                       'eye opening must not decrease).')
        else:
            message = ('The generated image changed facial feature proportions '
                       f"({reported} changed {changes[reported]:+.1%}; "
                       f"limit {limits[reported]:.1%}).")
        if report['measurementNeedsReview']:
            message += ' Difference is at most one pixel; landmark uncertainty requires review, not a confirmed anatomical change.'
        raise SpikeError('QUALITY_CHECK_FAILED', message, report)
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
