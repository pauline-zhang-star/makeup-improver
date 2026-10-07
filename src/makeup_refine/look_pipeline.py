"""Validate a model-designed look, generate, then explain the resulting pixels."""
import numpy as np
from pydantic import ValidationError
from .imaging import to_srgb, composite, edge_safe_composite
from .interfaces import LandmarkProvider, LookEditor, LookExplainer
from .look_models import MakeupStyle, LookComparison
from .look_annotations import annotation_anchors
from .look_mask import (makeup_mask, lip_mask, complexion_mask, direct_edit_mask,
                        lip_center_highlight_mask, outer_wing_mask, DirectMaskCache)
from .look_alignment import align_candidate, register_direct_candidate
from .look_composite import composite_complexion_base, preserve_complexion_texture
from .landmarks import validate_face, LIPS, INNER_LIPS
from .lip_blend import blend_full_lips
from .technique_catalog import TechniquePlan, MIN_DISTINCT_REGIONS, PLANNED_REGION_TARGET
from PIL import Image
from .comparison_evidence import build_comparison_evidence, unresolved_evidence
from .models import SpikeError
from .preflight import check_face, face_detail_metrics
from .quality import (validate_candidate_geometry, validate_facial_proportions,
                      validate_protected_pixels, region_metrics,
                      VisibilityThresholds)


SELECTED_REGION_THRESHOLDS = VisibilityThresholds(
    min_mean_delta=2.0, max_mean_delta=35.0,
    pixel_delta=3.0, min_changed_fraction=.20)


def selected_region_change_metrics(original, enhanced, points, style, selected, mask_for=None):
    """Measure whether each selected technique changed its own mask region."""
    masks = [(mask_for([item]) if mask_for else
              direct_edit_mask(original.size, points, style, [item])) for item in selected]
    measurements = region_metrics(original, enhanced, masks,
                                  thresholds=SELECTED_REGION_THRESHOLDS)
    return [{'techniqueId': item['technique_id'], 'region': item['region'], **measurement}
            for item, measurement in zip(selected, measurements)]


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
                 on_plan=None, max_edit_attempts=2, on_attempt=None, on_aligned=None,
                 defer_guidance=False):
        if max_edit_attempts not in (1, 2):
            raise ValueError('Image generation is limited to one or two attempts.')
        self.editor, self.explainer, self.landmarks = editor, explainer, landmarks
        self.on_enhanced = on_enhanced
        self.on_candidate = on_candidate
        self.on_plan = on_plan
        self.max_edit_attempts = max_edit_attempts
        self.on_attempt = on_attempt
        self.on_aligned = on_aligned
        self.defer_guidance = defer_guidance

    def explain(self, original, enhanced, evidence=None):
        """May be retried on the saved pair without calling the image editor."""
        if original.size != enhanced.size:
            raise SpikeError('QUALITY_CHECK_FAILED', 'Image dimensions changed.')
        if np.array_equal(np.asarray(original), np.asarray(enhanced)):
            return {'status': 'completed_no_visible_changes', 'steps': [], 'assessments': [],
                    'preservationIssues': [], 'comparisonStatus': 'identical_pixels',
                    'comparisonEvidence': evidence, 'pendingChangeReviews': []}
        try:
            arguments = {'evidence': evidence} if evidence else {}
            comparison = LookComparison.model_validate(
                self.explainer.explain_changes(original, enhanced, **arguments))
        except (SpikeError, ValidationError) as exc:
            if isinstance(exc, SpikeError) and exc.code != 'EXPLANATION_FAILED':
                raise
            return {'status': 'instructions_unavailable', 'steps': [], 'assessments': [],
                    'preservationIssues': [], 'comparisonStatus': 'unavailable',
                    'errorCode': 'EXPLANATION_FAILED', 'pendingChangeReviews': [],
                    'comparisonEvidence': evidence,
                    'message': 'The comparison could not verify all eight areas. Retry the comparison without regenerating the image.'}
        assessments = [a.model_dump() for a in comparison.assessments]
        if comparison.preservationIssues:
            return {'status': 'rejected', 'steps': [], 'comparisonStatus': 'completed',
                    'preservationIssues': comparison.preservationIssues, 'assessments': assessments,
                    'comparisonEvidence': evidence, 'pendingChangeReviews': [],
                    'message': 'The comparison detected forbidden changes or visible makeup artifacts. This result needs review.'}
        steps = [step.model_dump() for step in comparison.visible_steps()]
        return {'status': 'completed' if steps else 'completed_no_visible_changes',
                'steps': steps, 'assessments': assessments,
                'preservationIssues': [], 'comparisonStatus': 'completed',
                'comparisonEvidence': evidence,
                'pendingChangeReviews': unresolved_evidence(evidence or {}, comparison)}

    def run(self, original, style=None):
        style = MakeupStyle(style or MakeupStyle.AUTO)
        points, _ = check_face(original, self.landmarks)
        plan = TechniquePlan.model_validate(self.editor.plan_techniques(original, style, points))
        if self.on_plan:
            self.on_plan(plan)
        plan_report = {'inputQuality': face_detail_metrics(original, points),
                       'annotationAnchors': annotation_anchors(points),
                       'techniquePlan': plan.model_dump(),
                       'selectedTechniques': [item['technique_id'] for item in plan.selected],
                       'planningMode': plan.selection_method,
                       'lookDirection': plan.look_direction,
                       'preservedAreas': plan.preserved_areas,
                       'rejectedProposals': plan.rejected_proposals,
                       'plannedDistinctRegionsTarget': PLANNED_REGION_TARGET,
                       'plannedTargetMet': len({item['region'] for item in plan.selected}) >= PLANNED_REGION_TARGET,
                       'aestheticThresholdsUsed': plan.selection_method == 'legacy_threshold_recipe',
                       'thresholdsEmpiricallyCalibrated': False}
        if getattr(self.editor, 'last_technique_analysis', None) is not None:
            plan_report['techniqueAnalysis'] = self.editor.last_technique_analysis
        if not plan.selected:
            enhanced = original.copy()
            if self.on_enhanced:
                self.on_enhanced(enhanced)
            return enhanced, {**plan_report, 'status': ('planning_rejected' if plan.rejected_proposals
                                                       else 'completed_no_changes'),
                              'requestedStyle': style.value, 'steps': [], 'assessments': [],
                              'comparisonStatus': ('skipped_invalid_plan' if plan.rejected_proposals
                                                   else 'skipped_no_selected_techniques'),
                              **({'message': 'All proposed techniques failed local validation. See rejectedProposals.'}
                                 if plan.rejected_proposals else {}),
                              **summarize_observed_changes([], []),
                              'imageEditCalls': 0, 'humanReviewRequired': True}
        complexion_enabled = any(item['region'] == 'foundation' for item in plan.selected)
        masks = DirectMaskCache(original.size, points, style)
        mask = masks.mask_for(plan.selected)
        attempts, correction = [], None
        for attempt in range(1, self.max_edit_attempts + 1):
            arguments = {'correction': correction} if correction else {}
            alignment, deviation = {}, None
            checkpoints = {key: {'status': 'not_run'} for key in
                           ('generation', 'registration', 'compositing', 'region_measurement',
                            'landmark_geometry', 'facial_proportions', 'protected_pixels', 'region_visibility')}
            active_check = 'generation'
            def passed(name, details=None):
                checkpoints[name] = {'status': 'passed', 'details': details}

            try:
                candidate = to_srgb(self.editor.enhance(original, style, mask, plan, **arguments))
                passed('generation')
                if self.on_candidate:
                    self.on_candidate(candidate)
                active_check = 'registration'
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
                passed('registration', alignment.copy())
                active_check = 'compositing'
                blush_items = [item for item in plan.selected if item.get('region') == 'blush']
                eye_items = [item for item in plan.selected
                             if item.get('region') in {'eyeliner', 'eyeshadow', 'lashes'}]
                image_scale = np.asarray(original.size)
                eye_span = float(np.linalg.norm(
                    (np.asarray(points[263]) - np.asarray(points[33])) * image_scale))
                eye_mask = (masks.mask_for(eye_items)
                            if eye_items else None)
                pigment_items = [item for item in plan.selected
                                 if item.get('region') in {'nose_contour', 'foundation'}]
                pigment_mask = masks.mask_for(pigment_items) if pigment_items else None
                if blush_items:
                    other_items = [item for item in plan.selected if item.get('region') != 'blush']
                    blush_mask = masks.mask_for(blush_items)
                    other_mask = (masks.mask_for(other_items)
                                  if other_items else None)
                    enhanced, composite_report = edge_safe_composite(
                        original, aligned, mask, soft_mask=blush_mask, hard_mask=other_mask,
                        soft_feather_pixels=max(4, eye_span * .045),
                        outer_feather_mask=eye_mask, outer_feather_pixels=max(3, eye_span * .025),
                        pigment_mask=pigment_mask)
                else:
                    enhanced, composite_report = edge_safe_composite(
                        original, aligned, mask, outer_feather_mask=eye_mask,
                        outer_feather_pixels=max(3, eye_span * .025),
                        pigment_mask=pigment_mask)
                complexion_texture_report = {'textureRestorationApplied': False}
                foundation_items = [item for item in plan.selected
                                    if item.get('region') == 'foundation']
                if foundation_items:
                    foundation_mask = masks.mask_for(foundation_items)
                    enhanced, complexion_texture_report = preserve_complexion_texture(
                        original, enhanced, foundation_mask)
                alignment['protectedRegionComposite'] = composite_report
                alignment['complexionTexture'] = complexion_texture_report
                passed('compositing', composite_report)
                active_check = 'region_measurement'
                selected_changes = selected_region_change_metrics(
                    original, enhanced, points, style, plan.selected, masks.mask_for)
                passed('region_measurement', selected_changes)
                alignment['selectedTechniqueChangeMetrics'] = selected_changes
                if self.on_aligned:
                    self.on_aligned(enhanced)
                active_check = 'landmark_geometry'
                deviation = validate_candidate_geometry(enhanced, original, points, self.landmarks)
                passed('landmark_geometry', {'maxLandmarkDeviation': deviation})
                active_check = 'facial_proportions'
                proportions = validate_facial_proportions(
                    enhanced, original, self.landmarks, style=style,
                    original_landmarks=points)
                passed('facial_proportions', proportions)
                active_check = 'protected_pixels'
                preservation = validate_protected_pixels(original, enhanced, mask)
                passed('protected_pixels', preservation)
                active_check = 'region_visibility'
                region_issues = [item for item in selected_changes
                                 if item['tooLittleChange'] or item['tooMuchChange']]
                if region_issues:
                    names = ', '.join(sorted({item['region'] for item in region_issues}))
                    raise SpikeError(
                        'QUALITY_CHECK_FAILED',
                        f'The selected {names} technique(s) fell outside the allowed visible-change band in their own edit regions.',
                        {'selectedTechniqueChangeMetrics': selected_changes})
                passed('region_visibility', selected_changes)
            except SpikeError as exc:
                checkpoints[active_check] = {'status': 'failed', 'message': exc.message, **exc.details}
                if exc.code not in {'QUALITY_CHECK_FAILED', 'NO_FACE', 'MULTIPLE_FACES'}:
                    if self.on_attempt:
                        self.on_attempt({'attempt': attempt, 'status': 'failed', 'errorCode': exc.code,
                                         'message': exc.message, 'checks': checkpoints})
                    raise
                correction = exc.message
                selected_changes = alignment.get('selectedTechniqueChangeMetrics', [])
                region_issues = [item for item in selected_changes
                                 if item['tooLittleChange'] or item['tooMuchChange']]
                if region_issues:
                    too_little = sorted({item['region'] for item in region_issues
                                         if item['tooLittleChange']})
                    too_much = sorted({item['region'] for item in region_issues
                                       if item['tooMuchChange']})
                    if too_little:
                        correction += (f' Also, the selected {", ".join(too_little)} region(s) '
                                       'did not show enough visible change inside their own masks; '
                                       'render those techniques clearly while keeping placement bounded.')
                    if too_much:
                        correction += (f' Also, the selected {", ".join(too_much)} region(s) '
                                       'changed too strongly; soften those selected techniques inside their masks.')
                record = {'attempt': attempt, 'status': 'rejected', 'errorCode': exc.code, 'checks': checkpoints,
                          'message': exc.message, 'alignment': alignment,
                          'maxLandmarkDeviation': deviation, **exc.details}
                attempts.append(record)
                if self.on_attempt:
                    self.on_attempt(record)
                if attempt == self.max_edit_attempts:
                    raise SpikeError(exc.code, exc.message,
                                     {**plan_report, 'generationAttempts': attempts, 'imageEditCalls': attempt}) from exc
                continue
            record = {'attempt': attempt, 'status': 'passed', 'alignment': alignment, 'checks': checkpoints,
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
                    'selectedTechniqueChangeMetrics': alignment['selectedTechniqueChangeMetrics'],
                    **proportions,
                    'maskCoverageFraction': float(np.mean(np.asarray(mask) > 0)),
                    'humanReviewRequired': True, **preservation}
        if self.on_enhanced:
            self.on_enhanced(enhanced)
        evidence = build_comparison_evidence(original, enhanced, points, style, plan.selected,
                                             mask_for=masks.mask_for)
        metadata['comparisonEvidence'] = evidence
        if self.defer_guidance:
            return enhanced, {**metadata, **plan_report, 'status': 'preview_ready',
                              'steps': [], 'assessments': [], 'comparisonStatus': 'awaiting_like',
                              'imageEditCalls': len(attempts), 'guidanceDeferred': True}
        explanation = self.explain(original, enhanced, evidence=evidence)
        planned_areas = {('eyebrows' if item['region'] == 'brows' else
                          'complexion' if item['region'] == 'foundation' else item['region'])
                         for item in plan.selected}
        allowed_areas = planned_areas | set(allowed_supplementary)
        all_observed = {step['area'] for step in explanation['steps']}
        explanation['filteredUnplannedObservedAreas'] = sorted(all_observed - allowed_areas)
        explanation['steps'] = [step for step in explanation['steps'] if step['area'] in allowed_areas]
        if proportions['mouthWidthReview']['status'] == 'needs_review':
            change = proportions['mouthWidthReview']['relativeChange']
            explanation.setdefault('pendingChangeReviews', []).append({
                'area': 'lips',
                'reason': (f'Measured mouth width changed {change:+.1%}, beyond the '
                           '8% review limit. Lip liner can change the visible outline; '
                           'inspect the paired images before accepting the lip shape.'),
                'before': 'Original lip outline',
                'after': 'Generated lip outline',
            })
        coverage = summarize_observed_changes(explanation['steps'], plan.selected,
                                              metadata['allowedSupplementaryAreas'])
        coverage['displayedStepCount'] = len(explanation['steps'])
        return enhanced, {**explanation, **metadata, **plan_report,
                          **coverage,
                          'imageEditCalls': len(attempts)}

    def recompose(self, original, candidate, style=None, selected=None):
        """Replay local compositing on a saved candidate; no editor or explainer call.

        ``selected`` should be the saved technique plan. Older runs without a
        plan use the legacy full-style mask and are explicitly flagged.
        """
        style = MakeupStyle(style or MakeupStyle.AUTO)
        points, _ = check_face(original, self.landmarks)
        fallback = not selected
        mask = (makeup_mask(original.size, points, style) if fallback
                else direct_edit_mask(original.size, points, style, selected))
        enhanced, metadata = self._compose(original, to_srgb(candidate), style, points,
                                            mask, selected=selected or [])
        return enhanced, {**metadata, 'status': 'instructions_unavailable', 'steps': [],
                          'assessments': [], 'comparisonStatus': 'pending_new_comparison',
                          'imageEditCalls': 0, 'comparisonCalls': 0,
                          'legacyFullStyleMaskFallback': fallback,
                          'message': 'Locally recomposited image. Compare this exact pair before showing makeup instructions.'}

    def _compose(self, original, candidate, style, points, mask, selected=(),
                 lips_selected=None, localized_lip_only=False, outer_wing_selected=None):
        aligned, alignment = align_candidate(original, candidate, points, self.landmarks)
        aligned_points = validate_face(self.landmarks.detect(aligned))
        lip_deviation = float(np.linalg.norm((np.asarray(aligned_points) -
                              np.asarray(points))[LIPS + INNER_LIPS], axis=1).max())
        # A saved plan already contains any selected foundation technique's
        # small landmark mask. Only old runs without a plan use the legacy
        # full-style complexion fallback.
        base_mask = complexion_mask(original.size, points) if (not selected and style != MakeupStyle.AUTO) else None
        base = composite_complexion_base(original, aligned, base_mask) if base_mask else original
        if lips_selected is None:
            lips_selected = (not selected) or any(item.get('region') == 'lips' for item in selected)
        if outer_wing_selected is None:
            outer_wing_selected = any(item.get('technique_id') == 'eyeliner_05' for item in selected)
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
