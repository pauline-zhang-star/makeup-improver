"""Select measured techniques, generate once, then explain the resulting pixels."""
import numpy as np
from pydantic import ValidationError
from .imaging import to_srgb, composite, edge_safe_composite
from .interfaces import LandmarkProvider, LookEditor, LookExplainer
from .look_models import MakeupStyle, LookComparison
from .look_annotations import annotation_anchors
from .look_mask import (makeup_mask, lip_mask, complexion_mask, direct_edit_mask,
                        lip_center_highlight_mask, outer_wing_mask)
from .look_alignment import align_candidate, register_direct_candidate
from .look_composite import composite_complexion_base
from .landmarks import validate_face, LIPS, INNER_LIPS
from .lip_blend import blend_full_lips
from .technique_catalog import TechniquePlan, MIN_DISTINCT_REGIONS, PLANNED_REGION_TARGET
from PIL import Image
from .models import SpikeError
from .preflight import check_face
from .quality import (validate_candidate_geometry, validate_facial_proportions,
                      validate_protected_pixels)


def summarize_observed_changes(steps, selected, allowed_supplementary_areas=()):
    """Count only changes in planned areas toward the visibility goal."""
    planned = {('eyebrows' if item['region'] == 'brows' else
                'complexion' if item['region'] == 'foundation' else item['region'])
               for item in selected}
    observed = {step['area'] for step in steps}
    confirmed = sorted(observed & planned)
    supplementary = observed & set(allowed_supplementary_areas) - planned
    return {'visibleChangeCount': len(observed),
            'confirmedPlannedChangeAreas': confirmed,
            'confirmedPlannedChangeCount': len(confirmed),
            'observedSupplementaryChangeAreas': sorted(supplementary),
            'unexpectedMakeupChanges': sorted(observed - planned - supplementary),
            'minimumVisibleChangesMet': len(confirmed) >= MIN_DISTINCT_REGIONS}


def scope_local_lip_guidance(steps, selected):
    """Constrain wording to the only lip pixels this technique can transfer."""
    lip_ids = {item['technique_id'] for item in selected if item['region'] == 'lips'}
    if lip_ids != {'lips_02'}:
        return steps
    for step in steps:
        if step['area'] == 'lips':
            step['after'] = ('A small light-catching accent appears at the center of the lower lip; '
                             'the outer lip color and outline stay as before.')
            step['instruction'] = ('Tap a little highlight or clear gloss at the center of the lower lip '
                                   'and blend it in place without changing the lip outline.')
    return steps


def reconcile_guidance_with_plan(explanation, selected):
    """Retain image-observed steps only where the edit actually allowed makeup."""
    coverage = summarize_observed_changes(explanation['steps'], selected)
    allowed = set(coverage['confirmedPlannedChangeAreas'])
    explanation['steps'] = [step for step in explanation['steps'] if step['area'] in allowed]
    scope_local_lip_guidance(explanation['steps'], selected)
    coverage['displayedStepCount'] = len(explanation['steps'])
    return coverage


class LookPipeline:
    def __init__(self, editor: LookEditor, explainer: LookExplainer,
                 landmarks: LandmarkProvider, on_enhanced=None, on_candidate=None,
                 on_plan=None, max_edit_attempts=2, on_attempt=None, on_aligned=None):
        if max_edit_attempts not in (1, 2):
            raise ValueError('Image generation is limited to one or two attempts.')
        self.editor, self.explainer, self.landmarks = editor, explainer, landmarks
        self.on_enhanced = on_enhanced
        self.on_candidate = on_candidate
        self.on_plan = on_plan
        self.max_edit_attempts = max_edit_attempts
        self.on_attempt = on_attempt
        self.on_aligned = on_aligned

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
        plan = TechniquePlan.model_validate(self.editor.plan_techniques(original, style, points))
        if self.on_plan:
            self.on_plan(plan)
        plan_report = {'techniquePlan': plan.model_dump(),
                       'selectedTechniques': [item['technique_id'] for item in plan.selected],
                       'plannedDistinctRegionsTarget': PLANNED_REGION_TARGET,
                       'plannedTargetMet': len({item['region'] for item in plan.selected}) >= PLANNED_REGION_TARGET,
                       'thresholdsEmpiricallyCalibrated': False}
        if getattr(self.editor, 'last_technique_analysis', None) is not None:
            plan_report['techniqueAnalysis'] = self.editor.last_technique_analysis
        if not plan.selected:
            enhanced = original.copy()
            if self.on_enhanced:
                self.on_enhanced(enhanced)
            return enhanced, {**plan_report, 'status': 'completed_no_changes',
                              'requestedStyle': style.value, 'steps': [], 'assessments': [],
                              'comparisonStatus': 'skipped_no_selected_techniques',
                              **summarize_observed_changes([], []),
                              'imageEditCalls': 0, 'humanReviewRequired': True}
        complexion_enabled = (style != MakeupStyle.AUTO or
                              any(item['region'] == 'foundation' for item in plan.selected))
        mask = direct_edit_mask(original.size, points, style, plan.selected,
                                include_complexion=complexion_enabled)
        attempts, correction = [], None
        for attempt in range(1, self.max_edit_attempts + 1):
            arguments = {'correction': correction} if correction else {}
            alignment, deviation = {}, None
            try:
                candidate = to_srgb(self.editor.enhance(original, style, mask, plan, **arguments))
                if self.on_candidate:
                    self.on_candidate(candidate)
                try:
                    aligned, alignment = register_direct_candidate(
                        original, candidate, points, self.landmarks, mask)
                except SpikeError as alignment_error:
                    recoverable_border = (alignment_error.code == 'QUALITY_CHECK_FAILED' and
                                          'lose too much frame content or overlap makeup' in alignment_error.message)
                    if not recoverable_border:
                        raise
                    # A modest camera shift can lose more than the strict
                    # diagnostic border budget. Align it first, then restore
                    # that border from the original before any makeup blend.
                    aligned, alignment = register_direct_candidate(
                        original, candidate, points, self.landmarks, mask,
                        max_restored_border=.08)
                    alignment['registrationFallback'] = 'expanded_border_recovery'
                enhanced, composite_report = edge_safe_composite(original, aligned, mask)
                alignment['protectedRegionComposite'] = composite_report
                if self.on_aligned:
                    self.on_aligned(enhanced)
                deviation = validate_candidate_geometry(enhanced, original, points, self.landmarks)
                proportions = validate_facial_proportions(enhanced, original, self.landmarks)
                preservation = validate_protected_pixels(original, enhanced, mask)
            except SpikeError as exc:
                if exc.code not in {'QUALITY_CHECK_FAILED', 'NO_FACE', 'MULTIPLE_FACES'}:
                    raise
                correction = exc.message
                record = {'attempt': attempt, 'status': 'rejected', 'errorCode': exc.code,
                          'message': exc.message, 'alignment': alignment,
                          'maxLandmarkDeviation': deviation, **exc.details}
                attempts.append(record)
                if self.on_attempt:
                    self.on_attempt(record)
                if attempt == self.max_edit_attempts:
                    raise SpikeError(exc.code, exc.message,
                                     {'generationAttempts': attempts, 'imageEditCalls': attempt}) from exc
                continue
            record = {'attempt': attempt, 'status': 'passed', 'alignment': alignment,
                      'maxLandmarkDeviation': deviation, **proportions, **preservation}
            attempts.append(record)
            if self.on_attempt:
                self.on_attempt(record)
            break
        allowed_supplementary = ['complexion'] if complexion_enabled else []
        metadata = {'requestedStyle': style.value,
                    'generationMode': 'direct_api_result',
                    'allowedSupplementaryAreas': allowed_supplementary,
                    'complexionMaskEnabled': complexion_enabled,
                    'spatialAlignment': alignment, 'generationAttempts': attempts,
                    'annotationAnchors': annotation_anchors(points),
                    'maxLandmarkDeviation': deviation,
                    **proportions,
                    'maskCoverageFraction': float(np.mean(np.asarray(mask) > 0)),
                    'humanReviewRequired': True, **preservation}
        if self.on_enhanced:
            self.on_enhanced(enhanced)
        explanation = self.explain(original, enhanced)
        planned_areas = {('eyebrows' if item['region'] == 'brows' else
                          'complexion' if item['region'] == 'foundation' else item['region'])
                         for item in plan.selected}
        allowed_areas = planned_areas | set(allowed_supplementary)
        all_observed = {step['area'] for step in explanation['steps']}
        explanation['filteredUnplannedObservedAreas'] = sorted(all_observed - allowed_areas)
        explanation['steps'] = [step for step in explanation['steps'] if step['area'] in allowed_areas]
        coverage = summarize_observed_changes(explanation['steps'], plan.selected,
                                              metadata['allowedSupplementaryAreas'])
        coverage['displayedStepCount'] = len(explanation['steps'])
        return enhanced, {**explanation, **metadata, **plan_report,
                          **coverage,
                          'imageEditCalls': len(attempts)}

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

    def _compose(self, original, candidate, style, points, mask, lips_selected=True,
                 localized_lip_only=False, outer_wing_selected=False):
        aligned, alignment = align_candidate(original, candidate, points, self.landmarks)
        aligned_points = validate_face(self.landmarks.detect(aligned))
        lip_deviation = float(np.linalg.norm((np.asarray(aligned_points) -
                              np.asarray(points))[LIPS + INNER_LIPS], axis=1).max())
        base_mask = complexion_mask(original.size, points) if style != MakeupStyle.AUTO else None
        base = composite_complexion_base(original, aligned, base_mask) if base_mask else original
        lips = lip_mask(original.size, points, style)
        other_mask = (mask if localized_lip_only else
                      Image.fromarray(np.where(np.asarray(lips) > 0, 0,
                                               np.asarray(mask)).astype(np.uint8)))
        base = composite(base, aligned, other_mask)
        if localized_lip_only:
            base = _directional_cosmetic_transfer(
                original, aligned, base, lip_center_highlight_mask(original.size, points),
                direction='brighten')
            enhanced, lip_blend = base, None
            lip_mode = 'localized_center_highlight'
        elif lips_selected:
            enhanced, lip_blend = blend_full_lips(base, aligned, points, aligned_points, lips)
            lip_mode = 'spatial_adaptive_poisson'
        else:
            enhanced, lip_blend = base, None
            lip_mode = 'unchanged'
        if outer_wing_selected:
            enhanced = _directional_cosmetic_transfer(
                original, aligned, enhanced, outer_wing_mask(original.size, points),
                direction='darken')
        deviation = validate_candidate_geometry(enhanced, original, points, self.landmarks)
        # Save the finished image BEFORE explaining it. No text can modify it afterward.
        if self.on_enhanced:
            self.on_enhanced(enhanced)
        report = dict(requestedStyle=style.value,
                      annotationAnchors=annotation_anchors(points),
                      maxLandmarkDeviation=deviation, humanReviewRequired=True,
                      alignment=alignment, lipTransferMode=lip_mode,
                      lipBlendQuality=lip_blend,
                      lipLandmarkDeviation=lip_deviation,
                      maskCoverageFraction=float(np.mean(np.asarray(mask) > 0)),
                      faceBaseStrength=.6 if base_mask else 0,
                      faceBaseCoverageFraction=float(np.mean(np.asarray(base_mask) > 0)) if base_mask else 0)
        return enhanced, report


def _directional_cosmetic_transfer(original, candidate, current, shape, direction):
    """Transfer only generated highlight or dark pigment inside a tight soft mask."""
    old = np.asarray(original.convert('RGB'), dtype=np.float32)
    new = np.asarray(candidate.convert('RGB'), dtype=np.float32)
    luminance_weights = np.array((.2126, .7152, .0722), dtype=np.float32)
    change = (new - old) @ luminance_weights
    if direction == 'darken':
        change = -change
    activation = np.clip((change - 6.) / 20., 0., 1.)
    opacity = np.rint(np.asarray(shape, dtype=np.float32) * activation).astype(np.uint8)
    return composite(current, candidate, Image.fromarray(opacity))
