"""Small set of geometry measurements derived from detected face landmarks."""
import math
import numpy as np


def landmark_measurements(points):
    xy = np.asarray(points, dtype=float)
    left_center = (xy[33] + xy[133]) / 2
    right_center = (xy[263] + xy[362]) / 2
    ied = float(np.linalg.norm(right_center - left_center))
    if not np.isfinite(ied) or ied < .03:
        return {}
    left_width = float(np.linalg.norm(xy[133] - xy[33]))
    right_width = float(np.linalg.norm(xy[263] - xy[362]))
    eye_gap = float(np.linalg.norm(xy[362] - xy[133])) / ied
    left_aspect = float(np.linalg.norm(xy[159] - xy[145])) / max(left_width, .001)
    right_aspect = float(np.linalg.norm(xy[386] - xy[374])) / max(right_width, .001)
    # Positive angle means the outer corners sit higher than the inner corners.
    left_tilt = math.degrees(math.atan2(xy[133, 1] - xy[33, 1], abs(xy[133, 0] - xy[33, 0])))
    right_tilt = math.degrees(math.atan2(xy[362, 1] - xy[263, 1], abs(xy[263, 0] - xy[362, 0])))
    return {
        'inter_eye_distance': eye_gap,
        'eye_tilt_angle': (left_tilt + right_tilt) / 2,
        'eye_aspect_ratio': (left_aspect + right_aspect) / 2,
        'nasal_width_ratio': float(np.linalg.norm(xy[129] - xy[358])) / ied,
        'lower_lip_fullness_estimate': float(np.linalg.norm(xy[17] - xy[14])) / ied,
    }


def override_landmark_values(analysis, points):
    """Use detector geometry instead of model-supplied numeric guesses.

    The model must still assert region visibility and confidence. Explicitly
    low-confidence measurements remain ineligible. A missing spatial value can
    be supplied by landmarks only when its region is confidently visible.
    """
    from .technique_catalog import TechniqueAnalysis, Measurement
    parsed = TechniqueAnalysis.model_validate(analysis)
    geometry_regions = {
        'inter_eye_distance': ('eyeliner', 'eyeshadow'),
        'eye_tilt_angle': ('eyeliner',),
        'eye_aspect_ratio': ('eyeliner',),
        'nasal_width_ratio': ('nose_contour',),
        'lower_lip_fullness_estimate': ('lips',),
    }
    for name, value in landmark_measurements(points).items():
        measured = parsed.measurements.get(name)
        if measured is not None:
            parsed.measurements[name] = Measurement(value=value,
                                                     detection_confidence=measured.detection_confidence)
        else:
            confidence = max((visible.detection_confidence
                              for region in geometry_regions[name]
                              if (visible := parsed.visibility.get(region)) is not None
                              and visible.value is True), default=0)
            if confidence >= .85:
                parsed.measurements[name] = Measurement(value=value,
                                                         detection_confidence=min(confidence, .9))
    return parsed


def promote_geometry_visible_regions(analysis, points):
    """Mark stable, anatomically visible makeup regions as available.

    Region visibility answers whether a feature can be edited, not whether it
    already needs makeup. Vision models sometimes return ``lips=false`` when
    they mean "no obvious lipstick". That incorrectly removes lips from the
    plan, even though the face landmarks clearly locate the mouth. Use the
    detector geometry as a local availability check so baseline planning can
    still include the lips. This does not claim that the lips need a change;
    it only keeps the region eligible for a selected, visible technique.
    """
    from .technique_catalog import TechniqueAnalysis, Measurement

    parsed = TechniqueAnalysis.model_validate(analysis)
    geometry = landmark_measurements(points)
    fullness = geometry.get('lower_lip_fullness_estimate')
    lip_measurement_evidence = any(name in parsed.measurements for name in (
        'lower_lip_fullness_estimate', 'lip_skin_contrast_ratio',
        'lip_undertone_hue_gap', 'lip_chroma_dominance_score'))
    if (fullness is not None and np.isfinite(fullness) and fullness > .015
            and lip_measurement_evidence):
        current = parsed.visibility.get('lips')
        confidence = min(max(current.detection_confidence if current else .9, .85), .9)
        parsed.visibility['lips'] = Measurement(value=True,
                                                 detection_confidence=confidence)
    return parsed
