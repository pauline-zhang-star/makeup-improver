import numpy as np
from .imaging import composite
from .interfaces import VisionProvider, ImageEditProvider, LandmarkProvider
from .landmarks import validate_face
from .models import Plan, SpikeError
from .preflight import check_image, validate_masks
from .quality import region_metrics, validate_candidate_geometry
from .guidance import guided_change


def validate_result(original, result, masks, points, detector):
    union = np.maximum.reduce([np.asarray(m) for m in masks])
    before, after = np.asarray(original), np.asarray(result)
    if not np.array_equal(before[union == 0], after[union == 0]):
        raise SpikeError("QUALITY_CHECK_FAILED", "Pixels changed outside the edit mask.")
    metrics = region_metrics(original, result, masks)
    if any(r["tooLittleChange"] for r in metrics):
        raise SpikeError("EDIT_TOO_WEAK", "The blended edit is below the visibility threshold; inspect a stronger local blend.")
    if any(r["tooMuchChange"] for r in metrics):
        raise SpikeError("EDIT_TOO_STRONG", "The blended edit exceeds the strength threshold; inspect a weaker local blend.")
    refined_points = np.asarray(validate_face(detector.detect(result)))
    original_points = np.asarray(points)
    if refined_points.shape != original_points.shape:
        raise SpikeError("QUALITY_CHECK_FAILED", "The landmark topology changed.")
    w, h = original.size
    x = np.clip((original_points[:, 0] * w).astype(int), 0, w - 1)
    y = np.clip((original_points[:, 1] * h).astype(int), 0, h - 1)
    protected = union[y, x] == 0
    deviation = np.linalg.norm(refined_points - original_points, axis=1)
    if not protected.any() or deviation[protected].max() > 0.012:
        raise SpikeError("QUALITY_CHECK_FAILED", "Unedited facial landmarks moved.")
    return {"outsideMaskIdentical": True, "meanRegionPixelDeltas": [r["meanPixelDelta"] for r in metrics],
            "regions": metrics,
            "maxProtectedLandmarkDeviation": float(deviation[protected].max()),
            "makeupImprovement": "requires_human_review",
            "identityAndRealism": "requires_human_review"}


class Pipeline:
    def __init__(self, vision: VisionProvider, editor: ImageEditProvider, landmarks: LandmarkProvider,
                 max_edit_attempts: int = 2, blend_strength: float = 0.5, on_candidate=None):
        if max_edit_attempts not in (1, 2):
            raise ValueError("Use one or two edit attempts")
        self.vision, self.editor, self.landmarks = vision, editor, landmarks
        self.max_edit_attempts = max_edit_attempts
        if not np.isfinite(blend_strength) or not 0 < blend_strength <= 1:
            raise ValueError("blend_strength must be greater than 0 and at most 1")
        self.blend_strength = blend_strength
        self.on_candidate = on_candidate

    def run(self, original):
        preflight = check_image(original, self.landmarks)
        points = preflight.points
        w, h = original.size
        plan = Plan.model_validate(self.vision.analyze_and_plan(original))
        report = {"status": "completed_no_changes", "analysis": plan.model_dump()["analysis"],
                  "changes": [], "attempts": 0, "phase1Validated": False,
                  "blendStrength": self.blend_strength, "blendSpace": "encoded_sRGB"}
        if not plan.changes:
            return None, None, report
        masks = [preflight.masks[change.area] for change in plan.changes]
        union = validate_masks(masks)
        for attempt in range(self.max_edit_attempts):
            try:
                edited = self.editor.edit(original, union, plan, attempt)
                if any(r["tooLittleChange"] for r in region_metrics(original, edited, masks)):
                    raise SpikeError("QUALITY_CHECK_FAILED", "The generated candidate did not demonstrate a visible technique change.")
                candidate_deviation = validate_candidate_geometry(edited, original, points, self.landmarks)
                # Retain only geometry-checked candidates, before strength validation.
                # Failed blend settings can be tuned locally without paying again.
                if self.on_candidate:
                    self.on_candidate(edited, union, masks, plan, attempt)
                result = composite(original, edited, union, self.blend_strength)
                checks = validate_result(original, result, masks, points, self.landmarks)
                checks["maxCandidateLandmarkDeviation"] = candidate_deviation
                changes = []
                for idx, (change, mask) in enumerate(zip(plan.changes, masks)):
                    changes.append(guided_change(change, mask, idx))
                report.update(status="completed", changes=changes, attempts=attempt + 1,
                              quality=checks)
                return result, union, report
            except SpikeError as exc:
                if exc.code not in {"QUALITY_CHECK_FAILED", "IMAGE_EDIT_FAILED", "NO_FACE",
                                    "MULTIPLE_FACES", "FACE_TOO_SMALL", "FEATURES_NOT_VISIBLE"}:
                    raise
                if attempt == self.max_edit_attempts - 1:
                    count = "two attempts" if self.max_edit_attempts == 2 else "one attempt"
                    raise SpikeError("QUALITY_CHECK_FAILED", f"Could not validate the refinement after {count}.") from exc
