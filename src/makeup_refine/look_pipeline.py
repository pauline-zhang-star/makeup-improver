"""Generate first, then explain the resulting pixels. No intermediate advice plan."""
import numpy as np
from pydantic import ValidationError
from .imaging import to_srgb, composite
from .interfaces import LandmarkProvider, LookEditor, LookExplainer
from .look_models import MakeupStyle, LookComparison
from .look_annotations import annotation_anchors
from .look_mask import makeup_mask, lip_mask, complexion_mask
from .look_alignment import align_candidate
from .look_composite import composite_complexion_base
from .landmarks import validate_face, LIPS, INNER_LIPS
from .lip_blend import blend_full_lips
from PIL import Image
from .models import SpikeError
from .preflight import check_face
from .quality import validate_candidate_geometry


class LookPipeline:
    def __init__(self, editor: LookEditor, explainer: LookExplainer,
                 landmarks: LandmarkProvider, on_enhanced=None, on_candidate=None):
        self.editor, self.explainer, self.landmarks = editor, explainer, landmarks
        self.on_enhanced = on_enhanced
        self.on_candidate = on_candidate

    def explain(self, original, enhanced):
        """May be retried on the saved pair without calling the image editor."""
        if original.size != enhanced.size:
            raise SpikeError('QUALITY_CHECK_FAILED', 'Image dimensions changed.')
        if np.array_equal(np.asarray(original), np.asarray(enhanced)):
            return {'status': 'completed_no_visible_changes', 'steps': [], 'assessments': [],
                    'preservationIssues': [], 'comparisonStatus': 'identical_pixels'}
        try:
            comparison = LookComparison.model_validate(self.explainer.explain_changes(original, enhanced))
        except (SpikeError, ValidationError) as exc:
            if isinstance(exc, SpikeError) and exc.code != 'EXPLANATION_FAILED':
                raise
            return {'status': 'instructions_unavailable', 'steps': [], 'assessments': [],
                    'preservationIssues': [], 'comparisonStatus': 'unavailable',
                    'errorCode': 'EXPLANATION_FAILED',
                    'message': 'The comparison could not verify all eight areas. Retry the comparison without regenerating the image.'}
        assessments = [a.model_dump() for a in comparison.assessments]
        if comparison.preservationIssues:
            return {'status': 'rejected', 'steps': [], 'comparisonStatus': 'completed',
                    'preservationIssues': comparison.preservationIssues, 'assessments': assessments,
                    'message': 'The comparison detected changes beyond makeup. This result needs review.'}
        steps = [step.model_dump() for step in comparison.visible_steps()]
        return {'status': 'completed' if steps else 'completed_no_visible_changes',
                'steps': steps, 'assessments': assessments,
                'preservationIssues': [], 'comparisonStatus': 'completed'}

    def run(self, original, style=None):
        style = MakeupStyle(style or MakeupStyle.AUTO)
        points, _ = check_face(original, self.landmarks)
        mask = makeup_mask(original.size, points, style)
        candidate = to_srgb(self.editor.enhance(original, style, mask))
        if self.on_candidate:
            self.on_candidate(candidate)
        enhanced, metadata = self._compose(original, candidate, style, points, mask)
        return enhanced, {**self.explain(original, enhanced), **metadata, 'imageEditCalls': 1}

    def recompose(self, original, candidate, style=None):
        """Replay local compositing on a saved candidate; no editor or explainer call."""
        style = MakeupStyle(style or MakeupStyle.AUTO)
        points, _ = check_face(original, self.landmarks)
        enhanced, metadata = self._compose(original, to_srgb(candidate), style, points,
                                            makeup_mask(original.size, points, style))
        return enhanced, {**metadata, 'status': 'instructions_unavailable', 'steps': [],
                          'assessments': [], 'comparisonStatus': 'pending_new_comparison',
                          'imageEditCalls': 0, 'comparisonCalls': 0,
                          'message': 'Locally recomposited image. Compare this exact pair before showing makeup instructions.'}

    def _compose(self, original, candidate, style, points, mask):
        aligned, alignment = align_candidate(original, candidate, points, self.landmarks)
        aligned_points = validate_face(self.landmarks.detect(aligned))
        lip_deviation = float(np.linalg.norm((np.asarray(aligned_points) -
                              np.asarray(points))[LIPS + INNER_LIPS], axis=1).max())
        base_mask = complexion_mask(original.size, points) if style != MakeupStyle.AUTO else None
        base = composite_complexion_base(original, aligned, base_mask) if base_mask else original
        lips = lip_mask(original.size, points, style)
        other_mask = Image.fromarray(np.where(np.asarray(lips) > 0, 0,
                                             np.asarray(mask)).astype(np.uint8))
        base = composite(base, aligned, other_mask)
        enhanced, lip_blend = blend_full_lips(base, aligned, points, aligned_points, lips)
        deviation = validate_candidate_geometry(enhanced, original, points, self.landmarks)
        # Save the finished image BEFORE explaining it. No text can modify it afterward.
        if self.on_enhanced:
            self.on_enhanced(enhanced)
        report = dict(requestedStyle=style.value,
                      annotationAnchors=annotation_anchors(points),
                      maxLandmarkDeviation=deviation, humanReviewRequired=True,
                      alignment=alignment, lipTransferMode='spatial_adaptive_poisson',
                      lipBlendQuality=lip_blend,
                      lipLandmarkDeviation=lip_deviation,
                      maskCoverageFraction=float(np.mean(np.asarray(mask) > 0)),
                      faceBaseStrength=.6 if base_mask else 0,
                      faceBaseCoverageFraction=float(np.mean(np.asarray(base_mask) > 0)) if base_mask else 0)
        return enhanced, report
