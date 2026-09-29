import copy

import pytest
from pydantic import ValidationError

from makeup_refine.look_models import MakeupStyle
from makeup_refine.look_mask import technique_mask
from makeup_refine.technique_measurements import (override_landmark_values,
                                                  promote_geometry_visible_regions)
from makeup_refine.look_prompts import enhancement_prompt
from makeup_refine.technique_catalog import (
    MAX_SELECTED_TECHNIQUES, TechniqueCatalog, TechniquePlan,
)


def measure(value, confidence=.96):
    return {'value': value, 'detection_confidence': confidence}


def analysis(proposals, measurements=None, visibility=None, lighting=True):
    return {
        'measurements': measurements or {},
        'visibility': visibility or {region: measure(True) for region in
                                     ('eyeliner', 'eyeshadow', 'brows', 'lips', 'blush',
                                      'nose_contour', 'foundation')},
        'proposals': proposals,
        'lighting_gate': measure(lighting),
    }


def placement(technique_id, intensity=.4):
    return {'technique_id': technique_id, 'intensity': intensity}


def color(technique_id, lightness=.02, chroma=.01, hue=0):
    return {'technique_id': technique_id, 'color_delta': {
        'color_space': 'OKLCH', 'delta_lightness': lightness,
        'delta_chroma': chroma, 'delta_hue_degrees': hue}}


def test_runtime_cap_is_seven_and_does_not_pad():
    catalog = TechniqueCatalog()
    assert catalog.data['global_rules']['max_total_suggestions_per_job'] == 7
    assert catalog.max_suggestions == MAX_SELECTED_TECHNIQUES == 7
    measurements = {
        'inter_eye_distance': measure(.85),
        'visible_lid_ratio': measure(.12),
        'socket_depth_estimate': measure(.8),
        'crease_visibility': measure(.1),
        'brow_density_gap_score': measure(.9),
        'brow_tail_fade_score': measure(.9),
        'lower_lip_fullness_estimate': measure(.06),
        'nasal_width_ratio': measure(.85),
        'bridge_flatness_estimate': measure(.9),
        'brow_visibility': measure(.98),
    }
    proposals = [placement(key) for key in (
        'eyeliner_01', 'eyeliner_03', 'eyeshadow_01', 'eyeshadow_02',
        'brow_04', 'brow_05', 'lips_02', 'nose_01', 'nose_02')]
    plan = catalog.select(analysis(proposals, measurements))
    assert len(plan.selected) == 7
    assert plan.max_total_suggestions == 7
    assert len({item['technique_id'] for item in plan.selected}) == 7
    assert all(item['evidence'] for item in plan.selected)
    few = catalog.select(analysis(proposals[:1], measurements))
    assert [item['technique_id'] for item in few.selected] == ['eyeliner_01']
    assert catalog.select(analysis([], measurements)).selected == []


def test_confidence_occlusion_and_missing_and_condition_abstain():
    catalog = TechniqueCatalog()
    base = analysis([color('eyeshadow_05', hue=5)], {
        'eyeshadow_undertone_hue_gap': measure(11),
        'undertone_confidence': measure(.95),
        'eyeshadow_detected': measure(True),
    })
    assert len(catalog.select(base).selected) == 1
    for change in (
        lambda x: x['measurements'].pop('eyeshadow_detected'),
        lambda x: x['measurements']['undertone_confidence'].update(detection_confidence=.7),
        lambda x: x['visibility']['eyeshadow'].update(value=False),
        lambda x: x['lighting_gate'].update(value=False),
    ):
        case = copy.deepcopy(base)
        change(case)
        assert catalog.select(case).selected == []


def test_caps_conflicts_and_disabled_brow_selection():
    catalog = TechniqueCatalog()
    measurements = {
        'lip_skin_contrast_ratio': measure(.1),
        'lip_chroma_dominance_score': measure(.9),
        'brow_asymmetry_score': measure(.9),
        'both_brows_detected': measure(True),
        'brow_visibility': measure(.95),
        'brow_hair_hue_gap': measure(11),
        'hair_detection_confidence': measure(.95),
    }
    proposals = [color('lips_01'), color('lips_04'),
                 placement('brow_07'), color('brow_03', hue=13)]
    plan = catalog.select(analysis(proposals, measurements))
    assert [item['technique_id'] for item in plan.selected] == ['lips_01']
    proposals[-1] = color('brow_03', hue=5)
    plan = catalog.select(analysis(proposals, measurements))
    assert {item['technique_id'] for item in plan.selected} == {'lips_01', 'brow_03'}


def test_plan_rejects_more_than_seven_and_prompt_uses_only_selected():
    with pytest.raises(ValidationError):
        TechniquePlan(catalog_version='1.3', threshold_status='experimental_not_calibrated',
                      measurement_source='test', selected=[{}] * 8)
    plan = TechniqueCatalog().select(analysis([placement('nose_02', .3)],
                                               {'bridge_flatness_estimate': measure(.9)}))
    prompt = enhancement_prompt(MakeupStyle.AUTO, plan)
    assert 'nose_02' in prompt
    assert 'finished strength 0.3' in prompt
    assert 'local compositing applies' not in prompt
    assert 'Do not add unselected feature edits' in prompt
    assert 'optional facial base makeup is allowed' in prompt
    assert 'softly fill and clean the brow arch' not in prompt


def test_nose_techniques_have_distinct_local_masks():
    points = [(0.5, 0.5)] * 478
    points[33], points[263] = (.35, .40), (.65, .40)
    for index, y in ((168, .46), (6, .48), (197, .50), (195, .52), (5, .54)):
        points[index] = (.5, y)
    points[129], points[358] = (.44, .55), (.56, .55)
    def masked(technique_id):
        return technique_mask((512, 512), points, MakeupStyle.AUTO, [
            {'technique_id': technique_id, 'region': 'nose_contour', 'intensity': .3}])
    side, bridge = masked('nose_01'), masked('nose_02')
    assert side.getpixel((round(.44 * 512), round(.55 * 512))) > 0
    bridge_sample = (256, round(.48 * 512))
    assert side.getpixel(bridge_sample) == 0
    assert bridge.getpixel(bridge_sample) > 0
    assert bridge.getpixel((round(.44 * 512), round(.55 * 512))) == 0


def test_measured_placement_can_be_selected_when_model_omits_proposals():
    catalog = TechniqueCatalog()
    raw = analysis([], {
        'lower_lip_fullness_estimate': measure(.09),
        'lip_skin_contrast_ratio': measure(.10),
    })
    complete = catalog.complete_placement_proposals(raw)
    selected = catalog.select(complete).selected
    assert [item['technique_id'] for item in selected] == [
        'eyeliner_05', 'eyeshadow_07', 'brow_06', 'lips_02', 'blush_01']
    assert len({item['region'] for item in selected}) == 5
    assert selected[0]['intensity'] == .7
    assert all(item.technique_id != 'lips_01' for item in complete.proposals)


def test_missing_local_geometry_is_added_only_for_confidently_visible_region():
    points = [(0.5, 0.5)] * 478
    points[33], points[133] = (.3, .4), (.4, .4)
    points[362], points[263] = (.6, .4), (.7, .4)
    points[17], points[14] = (.5, .62), (.5, .60)
    visible = {'lips': measure(True, .95)}
    measured = override_landmark_values(analysis([], visibility=visible), points)
    assert measured.measurements['lower_lip_fullness_estimate'].detection_confidence == .9
    hidden = override_landmark_values(analysis([], visibility={'lips': measure(False, .95)}), points)
    assert 'lower_lip_fullness_estimate' not in hidden.measurements
    low = override_landmark_values(analysis([], measurements={
        'lower_lip_fullness_estimate': measure(.5, .4)}, visibility=visible), points)
    assert low.measurements['lower_lip_fullness_estimate'].detection_confidence == .4


def test_visible_mouth_is_not_dropped_when_model_confuses_no_lipstick_with_occlusion():
    points = [(0.5, 0.5)] * 478
    points[33], points[133] = (.3, .4), (.4, .4)
    points[362], points[263] = (.6, .4), (.7, .4)
    points[17], points[14] = (.5, .62), (.5, .60)
    raw = analysis([], measurements={'lip_chroma_dominance_score': measure(.4)})
    raw['visibility']['lips'] = measure(False, .98)
    promoted = promote_geometry_visible_regions(raw, points)
    assert promoted.visibility['lips'].value is True
    assert promoted.visibility['lips'].detection_confidence == .9


def test_style_baselines_fill_five_distinct_visible_regions_without_claiming_defects():
    catalog = TechniqueCatalog()
    plan = catalog.select(catalog.complete_placement_proposals(analysis([])))
    assert [item['technique_id'] for item in plan.selected] == [
        'eyeliner_05', 'eyeshadow_07', 'brow_06', 'lips_02', 'blush_01']
    assert all(item['selection_basis'] == 'style_baseline' for item in plan.selected)
    assert all(item['evidence'][0]['feature'] == 'anatomical_region_visible'
               for item in plan.selected)
    assert len({item['region'] for item in plan.selected}) >= 5
    hidden = {region: measure(False) for region in
              ('eyeliner', 'eyeshadow', 'brows', 'lips', 'blush', 'nose_contour', 'foundation')}
    assert catalog.select(catalog.complete_placement_proposals(
        analysis([], visibility=hidden))).selected == []


def test_visible_brow_and_lip_fallbacks_fill_plan_when_blush_is_unavailable():
    catalog = TechniqueCatalog()
    visibility = {region: measure(True) for region in
                  ('eyeliner', 'eyeshadow', 'brows', 'lips', 'nose_contour', 'foundation')}
    visibility['blush'] = measure(False)
    plan = catalog.select(catalog.complete_placement_proposals(
        analysis([], visibility=visibility)))
    ids = [item['technique_id'] for item in plan.selected]
    assert ids == ['eyeliner_05', 'eyeshadow_07', 'brow_06', 'lips_02', 'nose_02']
    assert len({item['region'] for item in plan.selected}) >= 5
    assert all(item['selection_basis'] == 'style_baseline' for item in plan.selected)


def test_lowercase_color_space_and_visible_lid_are_normalized():
    catalog = TechniqueCatalog()
    raw = analysis([color('brow_01', lightness=-.03)], {
        'brow_skin_contrast': measure(.1),
        'brow_visibility': measure(.95),
        'hair_detection_confidence': measure(.95),
        'visible_lid_ratio': measure(.3),
    })
    raw['proposals'][0]['color_delta']['color_space'] = 'oklch'
    raw['visibility']['eyeshadow'] = measure(False)
    parsed = catalog.complete_placement_proposals(raw)
    assert parsed.visibility['eyeshadow'].value is True
    selected = catalog.select(parsed).selected
    assert 'brow_01' in [item['technique_id'] for item in selected]
    assert next(item for item in selected if item['technique_id'] == 'brow_01')[
        'color_delta']['color_space'] == 'OKLCH'
