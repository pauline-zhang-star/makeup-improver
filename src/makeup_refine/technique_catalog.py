"""Validated technique vocabulary and measured pre-edit selection.

Measured triggers abstain when evidence is missing. Explicit style baselines
can fill confidently visible regions. Thresholds remain experimental.
"""
import json
from pathlib import Path
from typing import Optional, Union
from pydantic import Field, field_validator, model_validator

from .models import StrictModel, SpikeError
from .look_models import MakeupStyle

CATALOG_PATH = Path(__file__).with_name('technique_mapping_table.json')
MIN_CONFIDENCE = .85
MAX_SELECTED_TECHNIQUES = 7
MIN_DISTINCT_REGIONS = 5
PLANNED_REGION_TARGET = 5
MAX_PLACEMENT_INTENSITY = .7
MAX_NOSE_INTENSITY = .35
PROVISIONAL_PLACEMENT_INTENSITY = {
    'eyeliner': .45, 'eyeshadow': .45, 'brows': .35,
    'lips': .45, 'nose_contour': .25, 'foundation': .35,
    'blush': .65,
}
PROVISIONAL_TECHNIQUE_INTENSITY = {'lips_02': .7, 'eyeliner_05': .7}
# These five are the normal everyday baseline. They are placement refinements,
# not defect claims, and are selected only when the anatomical region is visible.
STYLE_BASELINE_PRIORITY = (
    # Keep the core eye/brow/lip areas ahead of optional blush.
    'eyeliner_05', 'eyeshadow_07', 'brow_06', 'lips_02', 'blush_01',
    # These visible-only placements fill a fifth distinct region when a core
    # baseline area is occluded, without claiming a facial defect.
    'nose_02', 'foundation_02'
)
STYLE_BASELINE_FALLBACKS = {'brow_06', 'lips_02'}

# Style ranks suitable techniques; it does not make an invisible feature or an
# unsafe color edit eligible. Auto deliberately retains its existing ranking.
STYLE_TECHNIQUE_PRIORITY = {
    MakeupStyle.AUTO: STYLE_BASELINE_PRIORITY,
    MakeupStyle.NATURAL: ('eyeliner_05', 'eyeshadow_07', 'brow_06', 'lips_02',
                          'blush_01', 'nose_02', 'foundation_02'),
    MakeupStyle.WORK: ('brow_06', 'eyeliner_05', 'eyeshadow_07', 'foundation_02',
                       'lips_01', 'blush_01', 'nose_02'),
    MakeupStyle.KOREAN_SOFT: ('eyeshadow_07', 'blush_01', 'lips_01', 'eyeliner_05',
                              'brow_06', 'foundation_02', 'nose_02'),
    MakeupStyle.FRESH: ('blush_01', 'lips_01', 'eyeshadow_07', 'brow_06',
                        'eyeliner_05', 'foundation_02', 'nose_02'),
    MakeupStyle.DATE_NIGHT: ('eyeliner_02', 'eyeshadow_02', 'lips_01', 'brow_05',
                             'blush_01', 'nose_02', 'foundation_02'),
    MakeupStyle.SOPHISTICATED: ('brow_05', 'eyeliner_05', 'eyeshadow_07', 'lips_03',
                                'lips_01', 'nose_02', 'foundation_02'),
    MakeupStyle.SOFT_GLAM: ('eyeshadow_02', 'eyeliner_05', 'blush_01', 'lips_01',
                            'brow_06', 'nose_02', 'foundation_02'),
}

# Korean Soft favors a softly graduated tint. A slightly less pronounced
# lip-to-skin contrast still qualifies when the image has confident lip
# visibility and the model supplies a bounded, image-relative color delta.
STYLE_TRIGGER_OVERRIDES = {
    MakeupStyle.KOREAN_SOFT: {
        'lips_01': {'lip_skin_contrast_ratio': {'below_threshold': .25}},
    },
}
EXPERIMENTAL_THRESHOLDS = {
    'inter_eye_distance': {'above_threshold': .75, 'below_threshold': .55},
    'eye_tilt_angle': {'below_threshold': -4.},
    'eye_aspect_ratio': {'below_threshold': .20},
    'visible_lid_ratio': {'below_threshold': .22},
    'socket_depth_estimate': {'above_threshold': .72},
    'crease_visibility': {'below_threshold': .35},
    'eyeshadow_undertone_hue_gap': {'above_threshold': 9.},
    'undertone_confidence': {'above_threshold': .85},
    'eyeshadow_iris_contrast': {'below_threshold': .25},
    'iris_detection_confidence': {'above_threshold': .9},
    'brow_visibility': {'above_threshold': .85},
    'brow_skin_contrast': {'below_threshold': .20},
    'brow_hair_lightness_gap': {'above_threshold': .30},
    'hair_detection_confidence': {'above_threshold': .9},
    'brow_hair_hue_gap': {'above_threshold': 9.},
    'brow_density_gap_score': {'above_threshold': .72},
    'brow_tail_fade_score': {'above_threshold': .72},
    'brow_edge_definition': {'below_threshold': .28},
    'brow_asymmetry_score': {'above_threshold': .72},
    'lip_skin_contrast_ratio': {'below_threshold': .20},
    'lower_lip_fullness_estimate': {'below_threshold': .10},
    'lip_undertone_hue_gap': {'above_threshold': 9.},
    'lip_chroma_dominance_score': {'above_threshold': .72},
    'nasal_width_ratio': {'above_threshold': .75},
    'bridge_flatness_estimate': {'above_threshold': .72},
    'under_eye_darkness_score': {'above_threshold': .45},
    'cheekbone_highlight_estimate': {'below_threshold': .28},
}


class Measurement(StrictModel):
    value: Union[bool, float]
    detection_confidence: float = Field(ge=0, le=1)


class ColorDelta(StrictModel):
    color_space: str
    delta_lightness: float
    delta_chroma: float
    delta_hue_degrees: float

    @field_validator('color_space')
    @classmethod
    def normalize_color_space(cls, value):
        return value.upper()


class TechniqueProposal(StrictModel):
    technique_id: str
    intensity: Optional[float] = Field(default=None, ge=0, le=1)
    color_delta: Optional[ColorDelta] = None
    target_side: Optional[str] = None


class TechniqueAnalysis(StrictModel):
    measurements: dict[str, Measurement]
    visibility: dict[str, Measurement]
    proposals: list[TechniqueProposal] = Field(max_length=30)
    lighting_gate: Measurement

    @model_validator(mode='after')
    def expand_eye_visibility(self):
        # Vision providers often label the anatomical eye region simply "eyes".
        # Absence of existing eyeliner/shadow is not anatomical occlusion.
        eyes = self.visibility.get('eyes')
        if eyes is not None:
            self.visibility.setdefault('eyeliner', eyes)
            self.visibility.setdefault('eyeshadow', eyes)
        # A reliably measured visible lid is direct evidence that eyeshadow can
        # be placed, even if the model meant "no existing eyeshadow" by false.
        lid = self.measurements.get('visible_lid_ratio')
        liner = self.visibility.get('eyeliner')
        shadow = self.visibility.get('eyeshadow')
        if (shadow is not None and shadow.value is False and liner is not None
                and liner.value is True and lid is not None and not isinstance(lid.value, bool)
                and lid.value > .12 and lid.detection_confidence >= MIN_CONFIDENCE):
            self.visibility['eyeshadow'] = Measurement(
                value=True, detection_confidence=min(lid.detection_confidence,
                                                     liner.detection_confidence))
        return self


class TechniquePlan(StrictModel):
    catalog_version: str
    threshold_status: str
    measurement_source: str
    selected: list[dict]
    max_total_suggestions: int = MAX_SELECTED_TECHNIQUES

    @model_validator(mode='after')
    def capped(self):
        if (self.max_total_suggestions != MAX_SELECTED_TECHNIQUES or
                len(self.selected) > MAX_SELECTED_TECHNIQUES):
            raise ValueError('Technique selection exceeds the global cap.')
        return self


class TechniqueCatalog:
    def __init__(self, data=None, thresholds=None):
        self.data = data if data is not None else json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
        self.thresholds = thresholds if thresholds is not None else EXPERIMENTAL_THRESHOLDS
        self._validate()

    def thresholds_for_style(self, style=MakeupStyle.AUTO):
        """Return the explicit trigger values the planner should measure."""
        style = MakeupStyle(style or MakeupStyle.AUTO)
        thresholds = {feature: dict(values) for feature, values in self.thresholds.items()}
        for overrides in STYLE_TRIGGER_OVERRIDES.get(style, {}).values():
            for feature, comparators in overrides.items():
                thresholds.setdefault(feature, {}).update(comparators)
        return thresholds

    def _validate(self):
        if self.data.get('table_version') != '1.3':
            raise SpikeError('CONFIGURATION_ERROR', 'Unsupported technique table version.')
        source_cap = self.data['global_rules']['max_total_suggestions_per_job']
        if source_cap != MAX_SELECTED_TECHNIQUES:
            raise SpikeError('CONFIGURATION_ERROR', 'Technique selection cap does not match the current product rule.')
        self.max_suggestions = source_cap
        if (self.data['global_rules'].get('planned_region_target_when_visible') != PLANNED_REGION_TARGET or
                self.data['global_rules'].get('minimum_visible_changes_goal') != MIN_DISTINCT_REGIONS):
            raise SpikeError('CONFIGURATION_ERROR', 'Unexpected distinct-region goals.')
        self.entries = {}
        for region, data in self.data['regions'].items():
            for entry in data['entries']:
                technique_id = entry['id']
                if technique_id in self.entries or not technique_id.startswith(('brow_' if region == 'brows' else 'nose_' if region == 'nose_contour' else 'foundation_' if region == 'foundation' else region + '_')):
                    raise SpikeError('CONFIGURATION_ERROR', 'Duplicate or mismatched technique id.')
                self.entries[technique_id] = (region, entry)
        for region, data in self.data['regions'].items():
            for entry in data.get('excluded', []):
                if entry['excluded_id'] in self.entries:
                    raise SpikeError('CONFIGURATION_ERROR', 'Excluded technique is active.')
        for name in ('MAX_DELTA_L', 'MAX_DELTA_C', 'MAX_DELTA_H_DEGREES'):
            if self.data['color_adjustment_caps'][name] <= 0:
                raise SpikeError('CONFIGURATION_ERROR', 'Invalid color cap.')

    def _check(self, condition, analysis, threshold_overrides=None):
        threshold_overrides = threshold_overrides or {}
        if 'all_of' in condition:
            evidence = []
            for part in condition['all_of']:
                matched = self._check(part, analysis, threshold_overrides)
                if matched is None:
                    return None
                evidence.extend(matched)
            return evidence
        feature = condition['feature']
        comparator = condition['comparator']
        if isinstance(feature, list):
            if comparator != 'matches_downturned_or_elongated':
                return None
            for name in feature:
                matched = self._check({'feature': name, 'comparator': 'below_threshold'},
                                      analysis, threshold_overrides)
                if matched is not None:
                    return matched
            return None
        measurement = (analysis.lighting_gate if feature == 'lighting_gate'
                       else analysis.measurements.get(feature))
        if measurement is None or measurement.detection_confidence < MIN_CONFIDENCE:
            return None
        value = measurement.value
        if comparator in ('true', 'pass'):
            if value is not True:
                return None
            threshold = None
        elif comparator in ('above_threshold', 'below_threshold'):
            threshold = threshold_overrides.get(feature, {}).get(
                comparator, self.thresholds.get(feature, {}).get(comparator))
            if threshold is None or isinstance(value, bool):
                return None
            if comparator == 'above_threshold' and not value > threshold:
                return None
            if comparator == 'below_threshold' and not value < threshold:
                return None
        else:
            return None
        return [dict(feature=feature, measured_value=value, threshold_used=threshold,
                     comparator=comparator, detection_confidence=measurement.detection_confidence)]

    def _strength(self, proposal, entry, region):
        if entry['adjustment_type'] == 'placement':
            cap = MAX_NOSE_INTENSITY if region == 'nose_contour' else MAX_PLACEMENT_INTENSITY
            if proposal.intensity is None or proposal.color_delta is not None or proposal.intensity > cap:
                return None
            return {'intensity': proposal.intensity}
        delta = proposal.color_delta
        caps = self.data['color_adjustment_caps']
        if proposal.intensity is not None or delta is None or delta.color_space != caps['color_space']:
            return None
        if (abs(delta.delta_lightness) > caps['MAX_DELTA_L'] or
                abs(delta.delta_chroma) > caps['MAX_DELTA_C'] or
                abs(delta.delta_hue_degrees) > caps['MAX_DELTA_H_DEGREES']):
            return None  # Drop excessive color requests; never clip them.
        return {'color_delta': delta.model_dump()}

    def complete_placement_proposals(self, analysis):
        """Use measured triggers when the vision model omits a placement candidate.

        This adds only vocabulary entries, never final selections. The normal
        visibility, confidence, threshold, and conflict gates still run in select.
        Color adjustments require a model-supplied signed delta and are not added.
        """
        analysis = TechniqueAnalysis.model_validate(analysis).model_copy(deep=True)
        proposed = {item.technique_id for item in analysis.proposals}
        for technique_id, (region, entry) in self.entries.items():
            if (entry['adjustment_type'] != 'placement' or entry.get('enabled') is False
                    or technique_id in proposed):
                continue
            analysis.proposals.append(TechniqueProposal(
                technique_id=technique_id,
                intensity=PROVISIONAL_TECHNIQUE_INTENSITY.get(
                    technique_id, PROVISIONAL_PLACEMENT_INTENSITY[region])))
        return analysis

    def select(self, analysis, style=MakeupStyle.AUTO):
        style = MakeupStyle(style or MakeupStyle.AUTO)
        style_priorities = STYLE_TECHNIQUE_PRIORITY[style]
        threshold_overrides = STYLE_TRIGGER_OVERRIDES.get(style, {})
        analysis = TechniqueAnalysis.model_validate(analysis)
        brows = analysis.visibility.get('brows')
        if brows is not None and 'brow_visibility' not in analysis.measurements:
            analysis.measurements['brow_visibility'] = Measurement(
                value=1.0 if brows.value is True else 0.0,
                detection_confidence=brows.detection_confidence)
        eligible = []
        baseline_eligible = {}
        for proposal in analysis.proposals:
            item = self.entries.get(proposal.technique_id)
            if item is None:
                continue
            region, entry = item
            if entry.get('enabled') is False:
                continue
            visible = analysis.visibility.get(region)
            if visible is None or visible.value is not True or visible.detection_confidence < MIN_CONFIDENCE:
                continue
            baseline = bool(entry.get('style_baseline'))
            fallback = (proposal.technique_id in STYLE_BASELINE_FALLBACKS and
                        entry['adjustment_type'] == 'placement')
            # A fallback remains a measured technique when its own trigger is
            # satisfied.  It becomes a visibility-only baseline only when the
            # trigger is unavailable, so strong evidence keeps its ranking.
            measured_evidence = (None if baseline else
                                 self._check(entry['trigger'], analysis,
                                             threshold_overrides.get(proposal.technique_id)))
            if baseline or (fallback and measured_evidence is None):
                evidence = [dict(feature='anatomical_region_visible', measured_value=True,
                                 threshold_used=MIN_CONFIDENCE, comparator='true',
                                 detection_confidence=visible.detection_confidence)]
            else:
                evidence = measured_evidence
                if evidence is None:
                    continue
            regional = self.data['regions'][region].get('visibility_precondition')
            if regional:
                extra = self._check(regional, analysis,
                                    threshold_overrides.get(proposal.technique_id))
                if extra is None:
                    continue
                evidence += extra
            if entry.get('reference_color_source') == 'hair_detection':
                extra = self._check({'feature': 'hair_detection_confidence',
                                     'comparator': 'above_threshold'}, analysis,
                                    threshold_overrides.get(proposal.technique_id))
                if extra is None:
                    continue
                evidence += extra
            if proposal.technique_id in self.data['hue_shift_entries_gated_by_lighting_check']:
                if (analysis.lighting_gate.value is not True or
                        analysis.lighting_gate.detection_confidence < MIN_CONFIDENCE):
                    continue
            strength = self._strength(proposal, entry, region)
            if strength is None:
                continue
            confidence = min([visible.detection_confidence] +
                             [item['detection_confidence'] for item in evidence])
            result = {'technique_id': proposal.technique_id, 'region': region,
                      'adjustment_type': entry['adjustment_type'],
                      'technique': entry['technique'],
                      'instruction': entry['instruction_template'],
                      'selection_basis': ('style_baseline'
                                          if (baseline or (fallback and measured_evidence is None))
                                          else 'measured_trigger'),
                      'evidence': evidence, 'detection_confidence': confidence,
                      **strength, 'target_side': proposal.target_side}
            if baseline or (fallback and measured_evidence is None):
                baseline_eligible[proposal.technique_id] = result
            else:
                eligible.append((confidence, proposal.technique_id, result))
        # Reserve room for distinct regions before adding second techniques
        # within an area. Conflicts still apply in both passes.
        selected = []
        seen = set()

        def add_result(technique_id, result):
            if technique_id in seen or len(selected) >= self.max_suggestions:
                return False
            region, entry = self.entries[technique_id]
            if any(other in seen for other in entry.get('mutually_exclusive_with', [])):
                return False
            if any(other in seen and self.entries[other][0] == region and
                   result['target_side'] == selected_item['target_side']
                   for other in entry.get('cannot_target_same_brow_as', [])
                   for selected_item in selected if selected_item['technique_id'] == other):
                return False
            selected.append(result)
            seen.add(technique_id)
            return True

        ranked = sorted(eligible, key=lambda row: (-row[0], row[1]))
        eligible_by_id = {technique_id: result for _, technique_id, result in ranked}

        # Named style preferences choose which suitable edits lead the plan.
        # The original Auto confidence-first ordering remains unchanged.
        if style == MakeupStyle.AUTO:
            for _, technique_id, result in ranked:
                if result['region'] not in {item['region'] for item in selected}:
                    add_result(technique_id, result)
        else:
            for technique_id in style_priorities:
                result = eligible_by_id.get(technique_id)
                if result is not None and result['region'] not in {
                        item['region'] for item in selected}:
                    add_result(technique_id, result)
            for _, technique_id, result in ranked:
                if result['region'] not in {item['region'] for item in selected}:
                    add_result(technique_id, result)

        # Fill toward five distinct regions with visible-only styling options
        # in the selected style's order. These entries have visibility as
        # their suitability evidence; they never assert a facial defect.
        for technique_id in style_priorities:
            if len({item['region'] for item in selected}) >= PLANNED_REGION_TARGET:
                break
            result = baseline_eligible.get(technique_id)
            if (result is None or result['region'] in {item['region'] for item in selected}
                    or len(selected) >= self.max_suggestions):
                continue
            add_result(technique_id, result)
        for _, technique_id, result in ranked:
            add_result(technique_id, result)
        return TechniquePlan(catalog_version=self.data['table_version'],
                             threshold_status='experimental_not_calibrated',
                             measurement_source='vision_estimate_with_local_geometry',
                             selected=selected,
                             max_total_suggestions=self.max_suggestions)
