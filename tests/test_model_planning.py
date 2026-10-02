import copy
import pytest
from pydantic import ValidationError
from makeup_refine.model_planning import LookDesign, validate_design, planning_prompt, REGIONS
from makeup_refine.look_models import MakeupStyle
from makeup_refine.technique_catalog import TechniqueCatalog


def evidence(region='brows', **changes):
    value = dict(region=region, current_state='bare', pigment_source='natural_feature',
                 operation='enhance', purpose='style_adaptation', confidence=.95,
                 visual_cues=['natural_color_visible'], observation='Natural pigment and edges are visible.',
                 target_effect='More definition within the current outline.',
                 style_reason='Coordinate definition with the requested look.')
    value.update(changes)
    return value


def proposal(tid='brow_04', **kwargs):
    value = dict(technique_id=tid, intensity=.4,
                 observation='There are small visible gaps toward the brow tail.',
                 style_reason='A groomed brow balances the more saturated lip.',
                 application='Fill gaps with fine strokes within the original outline.')
    value.update(kwargs)
    region = TechniqueCatalog().entries.get(tid, ('brows', {}))[0]
    value.setdefault('structured_evidence', evidence(region))
    return value


def design(proposals=None):
    return dict(look_direction='Coordinated rose lip and softly framed eyes.',
                visibility={r: dict(value=True, detection_confidence=.95) for r in REGIONS},
                lighting_gate=dict(value=True, detection_confidence=.95),
                color_references={k: dict(value=True, detection_confidence=.95)
                                  for k in ('hair', 'iris', 'undertone')},
                proposals=[proposal()] if proposals is None else proposals)


def color(tid='lips_01', **delta):
    values=dict(color_space='OKLCH', delta_lightness=0, delta_chroma=.025, delta_hue_degrees=0)
    values.update(delta)
    return proposal(tid, intensity=None, color_delta=values)


def test_selects_only_model_actions_preserves_order_evidence_and_strength():
    source=design([color(), proposal()]); before=copy.deepcopy(source)
    plan=validate_design(source)
    assert [v['technique_id'] for v in plan.selected]==['lips_01','brow_04']
    assert plan.selected[0]['color_delta']['delta_chroma']==.025
    assert plan.selected[1]['intensity']==.4
    assert plan.selected[1]['evidence'][0]['observation']==source['proposals'][1]['observation']
    assert source==before
    assert plan.threshold_status=='aesthetic_thresholds_not_used'


def test_selected_technique_keeps_chinese_application_for_review_only():
    plan = validate_design(design([proposal(application_zh='沿原有眉形用细笔触填补空隙。')]))
    assert plan.selected[0]['application_zh'] == '沿原有眉形用细笔触填补空隙。'


def test_production_validator_never_calls_threshold_selector_or_filler(monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('legacy path used')
    for name in ('select','_check','complete_placement_proposals','thresholds_for_style'):
        monkeypatch.setattr(TechniqueCatalog, name, forbidden)
    assert len(validate_design(design()).selected)==1
    assert validate_design(design([])).selected==[]
    for style in MakeupStyle:
        prompt=planning_prompt(style)
        assert style.value in prompt
        assert 'below_threshold' not in prompt
        assert 'brow_density_gap_score' not in prompt


@pytest.mark.parametrize(('candidate','reason'),[
    (proposal('not_in_catalog'),'unknown_technique'),
    (proposal('brow_07'),'disabled_technique'),
    (proposal(intensity=.71),'invalid_or_excessive_strength'),
    (proposal('nose_01',intensity=.36),'invalid_or_excessive_strength'),
    (color(delta_chroma=.041),'invalid_or_excessive_strength'),
    (color(delta_chroma=float('nan')),'invalid_or_excessive_strength'),
    (proposal(intensity=0),'zero_effect'),
])
def test_invalid_actions_are_logged_and_never_replaced(candidate,reason):
    plan=validate_design(design([candidate]))
    assert plan.selected==[]
    assert plan.rejected_proposals==[dict(technique_id=candidate['technique_id'],reason=reason)]


@pytest.mark.parametrize(('value','confidence'),[(False,.99),(True,.84)])
def test_unavailable_regions_are_not_promoted_to_visible(value,confidence):
    d=design();d['visibility']['brows']=dict(value=value,detection_confidence=confidence)
    plan=validate_design(d)
    assert not plan.selected
    assert plan.rejected_proposals[0]['reason']=='region_unavailable_or_uncertain'


def test_conflicts_duplicates_and_preserved_areas():
    plan=validate_design(design([color(),color('lips_04',delta_chroma=-.02),color()]))
    assert len(plan.selected)==1
    assert [r['reason'] for r in plan.rejected_proposals]==['conflicts_with:lips_01','duplicate_technique']
    d=design();d['preserved_areas']=[dict(region='brows',reason='Already well defined.')]
    assert validate_design(d).rejected_proposals[0]['reason']=='contradicts_preserved_area'


def test_hue_requires_lighting_and_reference_even_outside_hue_named_entries():
    d=design([color(delta_hue_degrees=2)])
    d['lighting_gate']['value']=False
    assert validate_design(d).rejected_proposals[0]['reason']=='unreliable_lighting_for_hue'
    d['lighting_gate']['value']=True;d['color_references'].pop('undertone')
    assert validate_design(d).rejected_proposals[0]['reason']=='unreliable_undertone_color_reference'
    d=design([color('brow_01',delta_lightness=-.02,delta_chroma=0)])
    d['color_references'].pop('hair')
    assert validate_design(d).rejected_proposals[0]['reason']=='unreliable_hair_color_reference'


def test_required_reasoning_and_cap_are_enforced():
    for key in ('observation','style_reason','application'):
        p=proposal();p[key]='  '
        with pytest.raises(ValidationError): LookDesign.model_validate(design([p]))
    with pytest.raises(ValidationError): LookDesign.model_validate(design([proposal()]*8))
    d=design();d['visibility'].pop('lips')
    with pytest.raises(ValidationError): LookDesign.model_validate(d)


def test_real_response_with_both_rendering_parameters_null_is_invalid():
    for p in [proposal(intensity=None, color_delta=None),
              proposal('lips_01', intensity=None, color_delta=None)]:
        with pytest.raises(ValidationError):
            LookDesign.model_validate(design([p]))


def excess_brow_evidence(**changes):
    value = dict(pigment_source='applied_makeup', excess_applied_product=True, confidence=.95,
                 visual_cues=['solid_fill_between_hairs'],
                 observation='Opaque pencil fill covers the spaces between the hairs near the brow head.',
                 reason_to_reduce='Diffuse the heavy product at the brow head to retain shape without competing with the eye focus.')
    value.update(changes)
    return value


def test_auto_supports_reducing_existing_brow_and_lip_makeup():
    source = design([color('brow_02', delta_lightness=.025, delta_chroma=0),
                     color('lips_04', delta_chroma=-.025)])
    source['brow_makeup_evidence'] = excess_brow_evidence()
    for item in source['proposals']:
        item['structured_evidence'].update(current_state='excess_product', pigment_source='applied_makeup', operation='reduce_product', visual_cues=['product_buildup'])
    plan = validate_design(source)
    assert [item['technique_id'] for item in plan.selected] == ['brow_02', 'lips_04']
    assert plan.selected[0]['color_delta']['delta_lightness'] == .025
    assert plan.selected[1]['color_delta']['delta_chroma'] == -.025
    assert plan.selected[0]['brow_makeup_evidence'] == source['brow_makeup_evidence']
    assert not plan.rejected_proposals


@pytest.mark.parametrize('candidate', [color('brow_02', delta_lightness=-.02),
                                       color('brow_01', delta_lightness=.02),
                                       color('lips_04', delta_chroma=.02)])
def test_color_reduction_cannot_silently_become_an_increase(candidate):
    plan = validate_design(design([candidate]))
    assert not plan.selected
    assert plan.rejected_proposals[0]['reason'] == 'color_direction_contradicts_technique'


def test_style_intensity_reaches_planner_editor_and_reduction_guidance():
    from makeup_refine.look_prompts import enhancement_prompt, comparison_prompt
    auto = planning_prompt(MakeupStyle.AUTO)
    assert 'target light, airy everyday makeup' in auto
    assert 'lips_04' in auto and 'negative delta_chroma' in auto
    candidate = color('lips_04', delta_chroma=-.025)
    candidate['structured_evidence'] = evidence('lips', current_state='excess_product',
        pigment_source='applied_makeup', operation='reduce_product', visual_cues=['product_buildup'])
    plan = validate_design(design([candidate]))
    prompt = enhancement_prompt(MakeupStyle.AUTO, plan)
    assert '"delta_chroma": -0.025' in prompt
    assert 'visible reduction in pigment' in prompt
    assert 'sheer, restrained lip' in prompt
    assert 'richer than Auto' in enhancement_prompt(MakeupStyle.DATE_NIGHT, plan)
    assert 'how to reduce or blend out' in comparison_prompt()


def test_strict_planning_schema_prevents_observed_format_failures():
    from makeup_refine.model_planning import planning_response_format
    fmt = planning_response_format()
    assert fmt['type'] == 'json_schema' and fmt['json_schema']['strict']
    schema = fmt['json_schema']['schema']
    assert set(schema['properties']['color_references']['properties']) == {'hair', 'iris', 'undertone'}
    color_schema = schema['$defs']['ColorTechnique']['properties']
    placement_schema = schema['$defs']['PlacementTechnique']['properties']
    assert 'brow_02' in color_schema['technique_id']['enum']
    assert 'brow_02' not in placement_schema['technique_id']['enum']
    assert color_schema['intensity']['type'] == 'null'
    assert placement_schema['color_delta']['type'] == 'null'
    assert schema['$defs']['ColorDelta']['properties']['color_space']['enum'] == ['OKLCH']
    def check(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for child in node.values(): check(child)
        elif isinstance(node, list):
            for child in node: check(child)
    check(schema)


@pytest.mark.parametrize(('evidence', 'reason'), [
    (None, 'brow_softening_requires_product_evidence'),
    (excess_brow_evidence(pigment_source='natural_hair'), 'natural_brow_color_is_not_excess_makeup'),
    (excess_brow_evidence(pigment_source='uncertain'), 'uncertain_brow_makeup_evidence'),
    (excess_brow_evidence(confidence=.84), 'uncertain_brow_makeup_evidence'),
    (excess_brow_evidence(excess_applied_product=False), 'no_excess_brow_makeup'),
    (excess_brow_evidence(visual_cues=[]), 'incomplete_brow_softening_evidence'),
    (excess_brow_evidence(observation='  '), 'incomplete_brow_softening_evidence'),
    (excess_brow_evidence(reason_to_reduce=''), 'incomplete_brow_softening_evidence'),
])
def test_brow_lightening_requires_product_evidence_without_filler(evidence, reason):
    source = design([color('brow_02', delta_lightness=.04, delta_chroma=0), color()])
    source['brow_makeup_evidence'] = evidence
    source['proposals'][0]['structured_evidence'] = None
    plan = validate_design(source)
    assert [x['technique_id'] for x in plan.selected] == ['lips_01']
    assert plan.rejected_proposals == [{'technique_id': 'brow_02', 'reason': reason}]
    audit = plan.validation_results[0]
    assert audit['status'] == 'rejected' and audit['browMakeupEvidence'] == evidence


def test_natural_brows_can_still_be_defined_without_makeup_evidence():
    source = design([proposal('brow_04')])
    source['brow_makeup_evidence'] = excess_brow_evidence(pigment_source='natural_hair',
                                                        excess_applied_product=False, visual_cues=[])
    assert validate_design(source).selected[0]['technique_id'] == 'brow_04'


def test_structured_output_requires_brow_evidence_field_but_allows_null():
    from makeup_refine.model_planning import planning_response_format
    schema = planning_response_format()['json_schema']['schema']
    assert 'brow_makeup_evidence' in schema['required']
    assert {'type': 'null'} in schema['properties']['brow_makeup_evidence']['anyOf']


@pytest.mark.parametrize('region', sorted(REGIONS))
def test_balanced_regions_can_adapt_to_style(region):
    from makeup_refine.model_planning import technique_evidence_rejection, TechniqueEvidence
    e = TechniqueEvidence(**evidence(region, current_state='balanced'))
    assert technique_evidence_rejection(e, region, 'style_action', None) is None

@pytest.mark.parametrize('changes,reason', [
    ({'region': 'lips'}, 'evidence_region_mismatch'),
    ({'current_state': 'uncertain'}, 'uncertain_technique_evidence'),
    ({'confidence': .84}, 'uncertain_technique_evidence'),
    ({'visual_cues': []}, 'incomplete_technique_evidence'),
    ({'target_effect': '  '}, 'incomplete_technique_evidence'),
    ({'pigment_source': 'applied_makeup'}, 'contradictory_product_evidence'),
])
def test_structured_evidence_failures_filter_only_one_proposal(changes, reason):
    bad = proposal(structured_evidence=evidence(**changes))
    plan = validate_design(design([bad, color()]))
    assert [x['technique_id'] for x in plan.selected] == ['lips_01']
    assert plan.rejected_proposals[0]['reason'] == reason


def test_missing_evidence_is_not_backfilled():
    p = proposal(); p.pop('structured_evidence')
    assert validate_design(design([p])).rejected_proposals[0]['reason'] == 'missing_technique_evidence'


def test_bare_brows_can_darken_without_excess_product():
    p = color('brow_01', delta_lightness=-.02, delta_chroma=0)
    assert validate_design(design([p])).selected


@pytest.mark.parametrize('tid,delta', [('brow_03', {'delta_lightness': .02}),
                                       ('lips_03', {'delta_chroma': -.02})])
def test_color_adjustment_cannot_bypass_product_reduction_gate(tid, delta):
    plan = validate_design(design([color(tid, **delta)]))
    assert plan.rejected_proposals[0]['reason'] == 'reduction_requires_applied_product'


def test_new_brow_evidence_does_not_require_legacy_slot():
    p = color('brow_02', delta_lightness=.02, delta_chroma=0)
    p['structured_evidence'] = evidence('brows', current_state='excess_product',
        pigment_source='applied_makeup', operation='reduce_product', visual_cues=['solid_product_fill'])
    plan = validate_design(design([p]))
    assert plan.selected[0]['structured_evidence'] == p['structured_evidence']


def test_wire_requires_nonnull_evidence_and_visibility_prompt_disambiguates_makeup():
    from makeup_refine.model_planning import planning_response_format
    schema = planning_response_format()['json_schema']['schema']
    for name in ('PlacementTechnique', 'ColorTechnique'):
        assert schema['$defs'][name]['properties']['structured_evidence'] == {'$ref': '#/$defs/TechniqueEvidence'}
    prompt = planning_prompt(MakeupStyle.AUTO)
    assert 'visible=true even without' in prompt
    assert 'no defect is required' in prompt
