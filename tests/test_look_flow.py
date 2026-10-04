from test_model_planning import evidence as technique_evidence
import base64
from io import BytesIO
import json
import numpy as np
from PIL import Image
import httpx
import pytest
from pydantic import ValidationError
from makeup_refine.cli import save_review
from makeup_refine.look_models import LookComparison, MakeupStyle, LOOK_AREAS
from makeup_refine.look_pipeline import (LookPipeline, _directional_cosmetic_transfer,
                                         reconcile_guidance_with_plan)
from makeup_refine.technique_catalog import TechniquePlan
from makeup_refine.look_prompts import enhancement_prompt
from makeup_refine.models import SpikeError
from makeup_refine.quality import validate_facial_proportions, validate_protected_pixels
from makeup_refine.providers import OpenAIProvider, png
from makeup_refine.imaging import edge_safe_composite
from makeup_refine.look_composite import preserve_complexion_texture
from test_pipeline import Detector, image


@pytest.fixture(autouse=True)
def stub_lip_solver_for_flow_tests(monkeypatch):
    """These tests use random pixels, so lip image-quality gates are tested elsewhere."""
    def compose(base, source, reference_points, candidate_points, old_lips):
        from makeup_refine.imaging import composite
        return composite(base, source, old_lips), {'qualityPassed': True,
                                                  'after': {'marginPixels': 0}}
    monkeypatch.setattr('makeup_refine.look_pipeline.blend_full_lips', compose)


def step(area='lips', changed=True, confidence=.95):
    return dict(area=area, changed=changed, confidence=confidence,
                before='Muted rose pigment.', after='More defined rose edge.',
                instruction='Trace the upper lip edge with the same rose shade, then blend inward.')


def assessments(steps):
    by_area = {s['area']: s for s in steps}
    result = []
    for area in LOOK_AREAS:
        s = by_area.get(area, step(area, False))
        result.append(dict(area=area, change='changed' if s['changed'] else 'unchanged',
                           confidence=s['confidence'], before=s['before'], after=s['after'],
                           instruction=s['instruction'] if s['changed'] else None))
    return result


class Provider:
    def __init__(self, steps=None, fail=False, issues=None):
        self.calls = []
        self.steps = [step()] if steps is None else steps
        self.fail, self.issues = fail, issues or []

    def plan_techniques(self, original, style, points):
        self.calls.append(('plan', style))
        return TechniquePlan(catalog_version='1.3', threshold_status='experimental_not_calibrated',
                             measurement_source='test_fixture', max_total_suggestions=7,
                             selected=[{'technique_id': 'lips_01', 'region': 'lips',
                                        'adjustment_type': 'color', 'technique': 'relative_tone_brighten',
                                        'instruction': 'Brighten the lip color.',
                                        'color_delta': {'color_space': 'OKLCH', 'delta_lightness': .02,
                                                        'delta_chroma': .01, 'delta_hue_degrees': 0},
                                        'evidence': [],
                                        'detection_confidence': .95}])

    def enhance(self, original, style, mask, plan=None):
        assert mask.mode == 'L' and mask.size == original.size
        self.mask = mask
        self.calls.append(('enhance', style))
        enhanced = original.copy()
        enhanced.paste((180, 80, 90), (200, 320, 300, 350))
        return enhanced

    def explain_changes(self, original, enhanced, evidence=None):
        self.calls.append(('explain', original, enhanced))
        if self.fail:
            raise SpikeError('EXPLANATION_FAILED', 'Steps unavailable.')
        return LookComparison(assessments=assessments(self.steps), preservationIssues=self.issues)


def test_auto_generates_before_explanation_and_saves_exact_final(image):
    provider = Provider()
    saved = []
    def save(enhanced):
        assert [c[0] for c in provider.calls] == ['plan', 'enhance']
        saved.append(enhanced)
    enhanced, result = LookPipeline(provider, provider, Detector(), save).run(image)
    assert [c[0] for c in provider.calls] == ['plan', 'enhance', 'explain']
    assert provider.calls[0][1] == MakeupStyle.AUTO
    assert provider.calls[2][1] is image
    assert provider.calls[2][2] is saved[0] is enhanced
    assert enhanced.getpixel((250, 330)) != image.getpixel((250, 330))
    assert result['generationMode'] == 'direct_api_result'
    assert result['requestedStyle'] == 'Auto'
    assert result['steps'][0]['instruction'] == step()['instruction']


@pytest.mark.parametrize('style', list(MakeupStyle))
def test_styles_are_forwarded_to_planning_and_editing(image, style):
    provider = Provider()
    _, result = LookPipeline(provider, provider, Detector()).run(image, style)
    assert provider.calls[0] == ('plan', style)
    assert provider.calls[1] == ('enhance', style)
    assert result['requestedStyle'] == style.value
    assert enhancement_prompt(style)


def test_auto_brief_requests_cosmetic_shape_without_anatomical_edit():
    prompt = enhancement_prompt(MakeupStyle.AUTO)
    assert 'light, soft everyday makeup' in prompt
    assert 'brow arch' in prompt and 'bridge highlight' in prompt
    assert 'cupid bow' in prompt and 'fuller' in prompt
    assert 'face reshaping' in prompt and 'mouth open or closed exactly' in prompt
    assert 'lock the original facial geometry' in prompt
    assert 'distance between the eyes' in prompt
    assert 'eye-to-nose distance' in prompt
    assert 'nose-to-mouth distance' in prompt
    assert 'Lock the hair silhouette' in prompt
    assert 'Auto mode is conservative' in prompt
    assert 'wider permitted selected-technique mask' not in prompt


def test_named_style_relaxes_cosmetic_rendering_without_relaxing_safety_rules():
    prompt = enhancement_prompt(MakeupStyle.KOREAN_SOFT)
    assert 'wider permitted selected-technique mask' in prompt
    assert 'at its own target intensity' in prompt
    assert 'does not automatically mean darker makeup' in prompt
    assert 'a decrease in eye opening' in prompt
    assert 'visible iris or eye white' in prompt
    assert 'clearly visible but sheer youthful pink flush' in prompt
    selected = [{'technique_id': 'blush_01', 'region': 'blush',
                 'adjustment_type': 'placement', 'technique': 'style_aware_cheek_blend',
                 'instruction': 'Apply a soft cheek tint.', 'intensity': .65}]
    assert 'perceptible in a normal-size before/after comparison' in enhancement_prompt(
        MakeupStyle.KOREAN_SOFT, {'selected': selected})


def test_selected_region_change_metrics_flag_an_omitted_blush(image):
    from makeup_refine.look_pipeline import selected_region_change_metrics

    points = np.asarray(Detector().detect(image)[0])
    blush = [{'technique_id': 'blush_01', 'region': 'blush',
              'adjustment_type': 'placement', 'intensity': .65}]
    unchanged = selected_region_change_metrics(
        image, image.copy(), points, MakeupStyle.KOREAN_SOFT, blush)
    assert unchanged[0]['tooLittleChange']

    from makeup_refine.look_mask import direct_edit_mask
    mask = np.asarray(direct_edit_mask(image.size, points, MakeupStyle.KOREAN_SOFT, blush)) > 128
    pixels = np.asarray(image).copy()
    pixels[mask] = (190, 85, 100)
    visible = selected_region_change_metrics(
        image, Image.fromarray(pixels), points, MakeupStyle.KOREAN_SOFT, blush)
    assert not visible[0]['tooLittleChange']


def test_noop_generation_fails_selected_region_visibility_check(image):
    provider = Provider()
    provider.enhance = lambda original, style, mask, plan=None: original.copy()
    with pytest.raises(SpikeError, match='fell outside the allowed visible-change band'):
        LookPipeline(provider, provider, Detector(), max_edit_attempts=1).run(image)


def test_named_style_allows_a_little_more_cosmetic_eye_opening(monkeypatch):
    from makeup_refine import quality

    before = {'leftEyeOpeningPixels': .20, 'rightEyeOpeningPixels': .20,
              'noseWidthPixels': .50, 'mouthWidthPixels': .60}
    after = {'leftEyeOpeningPixels': .214, 'rightEyeOpeningPixels': .20,
             'noseWidthPixels': .50, 'mouthWidthPixels': .60}
    values = iter((before, after))
    monkeypatch.setattr(quality, 'paired_facial_metrics',
                        lambda original, candidate, detector: (before, after, {}))

    report = quality.validate_facial_proportions(
        object(), object(), object(), style=MakeupStyle.KOREAN_SOFT)
    assert report['facialProportionMode'] == 'styled'
    assert report['facialProportionLimits']['leftEyeOpeningPixels'] == .08


def test_selected_style_does_not_open_full_face_mask_without_foundation(image):
    _, auto = LookPipeline(Provider(), Provider(), Detector()).run(image, MakeupStyle.AUTO)
    _, selected = LookPipeline(Provider(), Provider(), Detector()).run(image, MakeupStyle.SOFT_GLAM)
    assert auto['maskCoverageFraction'] < .1
    assert selected['maskCoverageFraction'] < .1
    assert not selected['complexionMaskEnabled']
    assert auto['generationMode'] == selected['generationMode'] == 'direct_api_result'


def test_unchanged_and_uncertain_areas_are_omitted(image):
    provider = Provider([step('lips'), step('eyebrows', False), step('blush', confidence=.4)])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert [s['area'] for s in result['steps']] == ['lips']


def test_only_observed_planned_areas_count_toward_five_step_goal():
    selected = [{'technique_id': 'lips_02', 'region': 'lips'},
                {'technique_id': 'eyeliner_05', 'region': 'eyeliner'},
                {'technique_id': 'blush_01', 'region': 'blush'},
                {'technique_id': 'brow_06', 'region': 'brows'},
                {'technique_id': 'foundation_02', 'region': 'foundation'}]
    explanation = {'steps': [step('eyeliner'), step('eyebrows'), step('blush'),
                             step('lips'), step('complexion')]}
    coverage = reconcile_guidance_with_plan(explanation, selected)
    assert coverage['visibleChangeCount'] == 5
    assert coverage['confirmedPlannedChangeCount'] == 5
    assert coverage['minimumVisibleChangesMet']
    assert coverage['unexpectedMakeupChanges'] == []
    assert [s['area'] for s in explanation['steps']] == ['eyeliner', 'eyebrows', 'blush', 'lips', 'complexion']
    assert 'center of the lower lip' in explanation['steps'][3]['instruction']


def test_unplanned_model_claims_cannot_satisfy_visibility_goal():
    selected = [{'technique_id': 'lips_02', 'region': 'lips'}]
    explanation = {'steps': [step('lips'), step('lashes'), step('complexion')]}
    coverage = reconcile_guidance_with_plan(explanation, selected)
    assert coverage['visibleChangeCount'] == 3
    assert coverage['confirmedPlannedChangeCount'] == 1
    assert not coverage['minimumVisibleChangesMet']
    assert [s['area'] for s in explanation['steps']] == ['lips']


def test_all_eight_areas_supported():
    areas = ['eyebrows', 'eyeliner', 'lashes', 'eyeshadow', 'nose_contour', 'blush', 'lips', 'complexion']
    result = LookComparison(assessments=assessments([step(a) for a in areas]), preservationIssues=[])
    assert len(result.visible_steps()) == 8
    with pytest.raises(ValidationError):
        LookComparison(assessments=assessments([step()])[:-1], preservationIssues=[])


def test_comparison_keeps_bilingual_instruction_for_the_same_visible_change():
    data = assessments([step('lips')])
    next(item for item in data if item['area'] == 'lips')['instruction_zh'] = '沿上唇边缘描画同色唇线，再向内晕染。'
    result = LookComparison(assessments=data, preservationIssues=[])
    assert result.visible_steps()[0].instruction_zh == '沿上唇边缘描画同色唇线，再向内晕染。'
    data[0]['instruction_zh'] = '未改变却添加了指导。'
    with pytest.raises(ValidationError):
        LookComparison(assessments=data, preservationIssues=[])


def test_no_change_does_not_fabricate_instructions(image):
    provider = Provider([])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert result['status'] == 'completed_no_visible_changes' and not result['steps']


def test_empty_technique_plan_preserves_original_and_skips_edit_and_comparison(image):
    provider = Provider()
    provider.plan_techniques = lambda original, style, points: TechniquePlan(
        catalog_version='1.3', threshold_status='experimental_not_calibrated',
        measurement_source='test_fixture', selected=[])
    enhanced, result = LookPipeline(provider, provider, Detector()).run(image)
    assert np.array_equal(np.asarray(enhanced), np.asarray(image))
    assert provider.calls == []
    assert result['status'] == 'completed_no_changes'
    assert result['imageEditCalls'] == 0
    assert result['techniquePlan']['max_total_suggestions'] == 7


def test_enhancement_prompt_uses_preselected_technique(image):
    provider = Provider()
    plan = provider.plan_techniques(image, MakeupStyle.AUTO, Detector().detect(image)[0])
    prompt = enhancement_prompt(MakeupStyle.AUTO, plan)
    assert 'lips_01' in prompt
    assert 'Brighten the lip color' in prompt
    assert 'optional facial base makeup is allowed' in prompt
    assert 'softly fill and clean the brow arch' not in prompt
    assert 'must not enter the eye opening' in prompt
    assert 'one coordinated look' in prompt
    assert 'must not be used to justify a larger edit area' in prompt
    assert 'must never make either eye opening smaller' in prompt
    assert 'small visible skin gap' in prompt
    assert 'blending upward and outward' in prompt
    assert 'bounded continuous makeup area' in prompt
    assert 'Wrinkles may look softer' in prompt
    assert 'never erase, blur, airbrush or reconstruct age cues' in prompt


def test_rejected_model_plan_makes_no_image_or_comparison_calls(image):
    from makeup_refine.model_planning import validate_design
    provider = Provider()
    rejected = validate_design({
        'look_direction': 'Keep the existing look.',
        'visibility': {r: {'value': True, 'detection_confidence': .95} for r in
                       ('eyeliner', 'eyeshadow', 'brows', 'lips', 'blush', 'nose_contour', 'foundation')},
        'lighting_gate': {'value': True, 'detection_confidence': .95},
        'region_decisions': [{'kind': 'propose', 'technique_id': 'unknown_technique', 'intensity': .3,
                       'observation': 'Visible brow tail.', 'style_reason': 'Balanced frame.',
                       'application': 'Fill sparse gaps.'}],
    })
    provider.plan_techniques = lambda original, style, points: rejected
    enhanced, result = LookPipeline(provider, provider, Detector()).run(image)
    assert result['status'] == 'planning_rejected'
    assert result['comparisonStatus'] == 'skipped_invalid_plan'
    assert result['rejectedProposals'][0]['reason'] == 'unknown_technique'
    assert result['planningMode'] == 'model_visual_reasoning_v1'
    assert result['aestheticThresholdsUsed'] is False
    assert result['imageEditCalls'] == 0 and provider.calls == []
    assert np.array_equal(enhanced, image)


def test_identical_pair_skips_paid_comparison(image):
    provider = Provider()
    result = LookPipeline(provider, provider, Detector()).explain(image, image.copy())
    assert result['status'] == 'completed_no_visible_changes'
    assert not provider.calls


def test_observed_base_makeup_is_allowed_but_does_not_replace_planned_techniques(image):
    from makeup_refine.look_pipeline import summarize_observed_changes
    provider = Provider(steps=[step('lips'), step('complexion')])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert result['allowedSupplementaryAreas'] == []
    assert result['filteredUnplannedObservedAreas'] == ['complexion']
    assert result['observedSupplementaryChangeAreas'] == []
    assert result['unexpectedMakeupChanges'] == []
    assert result['confirmedPlannedChangeCount'] == 1
    assert not result['minimumVisibleChangesMet']
    assert {s['area'] for s in result['steps']} == {'lips'}
    coverage = summarize_observed_changes([step('complexion')],
        [{'region': 'foundation'}], ['complexion'])
    assert coverage['confirmedPlannedChangeCount'] == 1
    assert coverage['observedSupplementaryChangeAreas'] == []


@pytest.mark.parametrize('confidence,changed', [(.7, True), (.95, False)])
def test_base_permission_does_not_invent_a_step(image, confidence, changed):
    provider = Provider(steps=[step('lips'), step('complexion', changed, confidence)])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert [s['area'] for s in result['steps']] == ['lips']
    assert result['observedSupplementaryChangeAreas'] == []


def test_facial_base_allowed_while_background_stays_protected():
    from makeup_refine.look_mask import direct_edit_mask, technique_mask, FACE_OVAL
    original = Image.new('RGB', (512, 512), (100, 100, 100))
    points = np.asarray(Detector().detect(original)[0])
    for index, angle in zip(FACE_OVAL, np.linspace(-np.pi / 2, 3 * np.pi / 2,
                                                  len(FACE_OVAL), endpoint=False)):
        points[index] = (.5 + .3 * np.cos(angle), .5 + .4 * np.sin(angle))
    plan = Provider().plan_techniques(original, MakeupStyle.AUTO, points)
    selected = np.asarray(technique_mask(original.size, points, MakeupStyle.AUTO, plan.selected))
    mask = direct_edit_mask(original.size, points, MakeupStyle.AUTO, plan.selected)
    base_only = (np.asarray(mask) > 0) & (selected == 0)
    assert base_only.sum() == 0
    pixels = np.asarray(original).copy()
    pixels[base_only] = (130, 120, 110)
    edited = Image.fromarray(pixels)
    assert validate_protected_pixels(original, edited, mask)['protectedMeanPixelDelta'] == 0
    assert mask.getpixel((0, 0)) == 0
    edited.paste((200, 200, 200), (0, 0, 512, 40))
    with pytest.raises(SpikeError, match='outside the selected makeup regions'):
        validate_protected_pixels(original, edited, mask)


def test_directional_transfer_keeps_only_the_requested_pigment_direction():
    original = Image.new('RGB', (3, 1), (100, 100, 100))
    candidate = Image.new('RGB', (3, 1))
    candidate.putdata([(40, 40, 40), (160, 160, 160), (100, 100, 100)])
    shape = Image.new('L', (3, 1), 255)
    dark = _directional_cosmetic_transfer(original, candidate, original, shape, 'darken')
    bright = _directional_cosmetic_transfer(original, candidate, original, shape, 'brighten')
    assert dark.getpixel((0, 0)) == (40, 40, 40)
    assert dark.getpixel((1, 0)) == (100, 100, 100)
    assert bright.getpixel((0, 0)) == (100, 100, 100)
    assert bright.getpixel((1, 0)) == (160, 160, 160)


def test_explanation_failure_keeps_image_and_retry_never_regenerates(image):
    provider = Provider(fail=True)
    enhanced, result = LookPipeline(provider, provider, Detector()).run(image)
    assert enhanced is not None and result['status'] == 'instructions_unavailable'
    provider.fail = False
    retry = LookPipeline(provider, provider, None).explain(image, enhanced)
    assert retry['status'] == 'completed'
    assert [c[0] for c in provider.calls] == ['plan', 'enhance', 'explain', 'explain']


def test_mouth_width_review_is_visible_without_rejecting_makeup(image, monkeypatch):
    from makeup_refine import look_pipeline
    original_check = look_pipeline.validate_facial_proportions

    def with_mouth_review(*args, **kwargs):
        report = original_check(*args, **kwargs)
        report['mouthWidthReview'] = {
            'status': 'needs_review', 'relativeChange': .081,
            'relativeLimit': .08, 'reason': 'Inspect lip outline.',
        }
        return report

    monkeypatch.setattr(look_pipeline, 'validate_facial_proportions', with_mouth_review)
    enhanced, result = LookPipeline(Provider(), Provider(), Detector()).run(image)
    assert enhanced is not None and result['status'] == 'completed'
    assert result['mouthWidthReview']['status'] == 'needs_review'
    assert any(item['area'] == 'lips' and '8%' in item['reason']
               for item in result['pendingChangeReviews'])


def test_preservation_issue_rejects_instructions(image):
    provider = Provider(issues=['glasses'])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert result['status'] == 'rejected' and result['steps'] == []


def test_dimension_failure_never_explains_or_saves(image):
    provider = Provider()
    provider.enhance = lambda original, style, mask, plan: Image.new('RGB', (256, 256))
    saved = []
    with pytest.raises(SpikeError, match='dimensions'):
        LookPipeline(provider, provider, Detector(), saved.append, max_edit_attempts=1).run(image)
    assert not saved and [c[0] for c in provider.calls] == ['plan']


def test_rejected_candidate_is_retained_before_geometry_check(image):
    provider = Provider()
    provider.enhance = lambda original, style, mask, plan: Image.new('RGB', (256, 256))
    candidate, accepted = [], []
    with pytest.raises(SpikeError, match='dimensions'):
        LookPipeline(provider, provider, Detector(), accepted.append, candidate.append,
                     max_edit_attempts=1).run(image)
    assert len(candidate) == 1 and not accepted


def test_dark_input_never_calls_provider():
    provider = Provider()
    with pytest.raises(SpikeError, match='light source'):
        LookPipeline(provider, provider, Detector()).run(Image.new('RGB', (512, 512)))
    assert not provider.calls


def test_provider_sends_original_then_both_images_without_advice(image):
    image = image.resize((768, 1024))
    requests = []
    enhanced = image.copy()
    enhanced.putpixel((200, 200), (180, 70, 90))
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('images/edits'):
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png(enhanced)).decode()}]})
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'assessments': assessments([step()]), 'preservationIssues': []})}}]})
    provider = OpenAIProvider('fake', 'vision', 'gpt-image-2')
    provider.client.close()
    provider.client = httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(handler))
    try:
        final = provider.enhance(image, MakeupStyle.SOFT_GLAM, Image.new('L', image.size, 255))
        comparison = provider.explain_changes(image, final)
    finally:
        provider.close()
    assert len(requests) == 2
    edit_body = requests[0].content
    assert b'Soft Glam' in edit_body and b'filename="mask.png"' in edit_body
    assert b'name="n"\r\n\r\n1' in edit_body
    body = json.loads(requests[1].content)
    assert 'Soft Glam' not in body['messages'][0]['content']
    pair = body['messages'][1]['content']
    assert pair[0]['text'] == 'ORIGINAL' and pair[2]['text'] == 'ENHANCED'
    for entry, expected in ((pair[1], image), (pair[3], final)):
        decoded = Image.open(BytesIO(base64.b64decode(entry['image_url']['url'].split(',')[1])))
        assert np.array_equal(decoded, expected)
    assert comparison.visible_steps()[0].area == 'lips'


def test_provider_plans_from_original_before_any_edit(image):
    requests = []
    answer = {
        'look_direction': 'Soft everyday definition, retaining the existing lip and eye makeup.',
        'visibility': {region: {'value': region == 'brows', 'detection_confidence': .98}
                       for region in ('eyeliner', 'eyeshadow', 'brows', 'lips', 'blush',
                                      'nose_contour', 'foundation')},
        'lighting_gate': {'value': True, 'detection_confidence': .98},
        'region_decisions': [{'kind': 'propose', 'technique_id': 'brow_04', 'intensity': .4,
                       'structured_evidence': technique_evidence('brows'),
                       'observation': 'The outer brow has visible small gaps.',
                       'style_reason': 'A softly filled brow balances the existing lip makeup.',
                       'application': 'Fill only the gaps with fine strokes inside the current outline.'}],
    }
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAIProvider('fake', 'vision', 'gpt-image-2')
    provider.client.close()
    provider.client = httpx.Client(base_url='https://api.openai.com/v1/',
                                   transport=httpx.MockTransport(handler))
    try:
        plan = provider.plan_techniques(image, MakeupStyle.AUTO, Detector().detect(image)[0])
    finally:
        provider.close()
    assert [item['technique_id'] for item in plan.selected] == ['brow_04']
    assert plan.max_total_suggestions == 7
    assert len(requests) == 1 and requests[0].url.path.endswith('chat/completions')
    body = json.loads(requests[0].content)
    assert body['response_format']['type'] == 'json_schema'
    assert body['response_format']['json_schema']['strict'] is True
    assert 'at most seven' in body['messages'][0]['content']
    assert body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')


def test_named_style_uses_model_proposals_without_recipe_or_score_replacement(image):
    answer = {
        'look_direction': 'A richer lip balanced by soft brow definition.',
        'visibility': {region: {'value': True, 'detection_confidence': .98}
                       for region in ('eyeliner', 'eyeshadow', 'brows', 'lips', 'blush',
                                      'nose_contour', 'foundation')},
        'lighting_gate': {'value': True, 'detection_confidence': .98},
        'region_decisions': [{'kind': 'propose', 'technique_id': 'lips_01',
            'structured_evidence': technique_evidence('lips'), 'color_delta': {
            'color_space': 'OKLCH', 'delta_lightness': .005, 'delta_chroma': .021,
            'delta_hue_degrees': 0}, 'observation': 'Existing lip pigment is muted rose.',
            'style_reason': 'A richer rose lip supports the evening eye makeup already present.',
            'application': 'Apply pigment evenly inside the existing lip boundary.'},
            {'kind': 'preserve', 'region': 'brows', 'reason': 'The brows already frame the eyes clearly.'}],
    }
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(answer)}}]})
    provider = OpenAIProvider('fake', 'vision', 'gpt-image-2')
    provider.client.close()
    provider.client = httpx.Client(base_url='https://api.openai.com/v1/',
                                   transport=httpx.MockTransport(handler))
    try:
        plan = provider.plan_techniques(image, MakeupStyle.DATE_NIGHT, Detector().detect(image)[0])
        saved = provider.last_technique_analysis
    finally:
        provider.close()
    assert [item['technique_id'] for item in plan.selected] == ['lips_01']
    assert plan.selected[0]['color_delta']['delta_chroma'] == .021
    assert plan.selected[0]['observation'] == answer['region_decisions'][0]['observation']
    assert plan.preserved_areas == [{'region': 'brows', 'reason': 'The brows already frame the eyes clearly.'}]
    assert saved['analysis_schema'] == plan.selection_method == 'model_visual_reasoning_v1'
    assert [item['kind'] for item in saved['region_decisions']] == ['propose', 'preserve']
    assert 'proposals' not in saved and 'preserved_areas' not in saved
    prompt = json.loads(requests[0].content)['messages'][0]['content']
    assert 'Date Night' in prompt and 'There is no fixed technique recipe' in prompt
    assert 'lip_skin_contrast_ratio' not in prompt
    assert 'below_threshold' not in prompt
    edit_prompt = enhancement_prompt(MakeupStyle.DATE_NIGHT, plan)
    assert answer['look_direction'] in edit_prompt
    assert answer['region_decisions'][0]['application'] in edit_prompt


def test_small_photo_uses_same_input_and_output_canvas_with_protected_padding():
    original = Image.new('RGB', (788, 524), (60, 70, 80))
    mask = Image.new('L', original.size, 0)
    mask.putpixel((394, 262), 255)
    requests = []
    def handler(request):
        requests.append(request)
        output = Image.new('RGB', (1008, 672), (180, 90, 100))
        return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png(output)).decode()}]})
    provider = OpenAIProvider('fake', 'vision', 'gpt-image-2')
    provider.client.close()
    provider.client = httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(handler))
    try:
        candidate = provider.enhance(original, MakeupStyle.AUTO, mask)
    finally:
        provider.close()
    assert candidate.size == original.size
    body = requests[0].content
    assert b'1008x672' in body
    sent_image = Image.open(BytesIO(body.split(b'filename="selfie.png"')[1].split(b'\r\n\r\n', 1)[1].split(b'\r\n--')[0]))
    sent_mask = Image.open(BytesIO(body.split(b'filename="mask.png"')[1].split(b'\r\n\r\n', 1)[1].split(b'\r\n--')[0]))
    assert sent_image.size == sent_mask.size == (1008, 672)
    assert sent_image.getpixel((0, 0)) == (60, 70, 80)
    assert sent_mask.getpixel((0, 0))[3] == 255
    assert np.count_nonzero(np.asarray(sent_mask)[..., 3] == 0) > 0


def test_report_uses_two_images_and_actual_instructions(tmp_path, image):
    provider = Provider()
    enhanced, result = LookPipeline(provider, provider, Detector()).run(image)
    result['steps'][0]['instruction'] = 'Use <rose> & blend inward.'
    save_review(tmp_path, image, enhanced, result)
    stored = json.loads((tmp_path / 'result.json').read_text())
    assert stored['originalImage'] == 'originalImage.png'
    assert stored['enhancedImage'] == 'enhancedImage.png'
    html = (tmp_path / 'review.html').read_text()
    assert 'How to Achieve This Look' in html
    assert 'Use &lt;rose&gt; &amp; blend inward.' in html
    assert 'pointerdown' in html and 'type="range"' in html
    assert 'Lift the outer tip' not in html


def test_rejected_api_candidate_stays_in_before_after_slider(tmp_path, image):
    original = image
    original.save(tmp_path / 'originalImage.png')
    candidate = Image.new('RGB', original.size, (170, 90, 120))
    candidate.save(tmp_path / 'candidateImage.png')
    aligned = Image.new('RGB', original.size, (100, 130, 170))
    aligned.save(tmp_path / 'aligned-candidate-1.png')

    report = {'status': 'failed', 'errorCode': 'QUALITY_CHECK_FAILED',
              'message': 'Eye opening decreased.', 'requestedStyle': 'Korean Soft',
              'candidateImage': 'candidateImage.png',
              'alignedCandidateImage': 'aligned-candidate-1.png'}
    save_review(tmp_path, original, None, report)

    stored = json.loads((tmp_path / 'result.json').read_text())
    html = (tmp_path / 'review.html').read_text()
    assert stored['enhancedImage'] is None
    assert 'Rejected candidate shown for comparison only' in html
    assert 'Rejected candidate only' in html
    assert 'type="range"' in html and 'pointerdown' in html
    assert html.count('data:image/png;base64,') >= 2


def test_cli_generates_saves_pair_and_retries_comparison_only(tmp_path, image, monkeypatch, capsys):
    from makeup_refine import cli
    import makeup_refine.providers
    import makeup_refine.landmarks
    photo = tmp_path / 'input.png'
    image.save(photo)
    provider = Provider(fail=True)
    provider.close = lambda: None
    detector = Detector()
    detector.close = lambda: None
    monkeypatch.setattr(makeup_refine.providers, 'OpenAIProvider', lambda *args: provider)
    monkeypatch.setattr(makeup_refine.landmarks, 'MediaPipeLandmarks', lambda *args: detector)
    monkeypatch.setattr(cli, 'get_api_key', lambda: 'test-only')
    output = tmp_path / 'result'
    monkeypatch.setattr('sys.argv', ['makeup-refine', str(photo), '--output', str(output),
                                  '--landmark-model', 'unused', '--vision-model', 'vision', '--edit-model', 'edit'])
    assert cli.main() == 0
    original_bytes = (output / 'originalImage.png').read_bytes()
    enhanced_bytes = (output / 'enhancedImage.png').read_bytes()
    assert json.loads((output / 'result.json').read_text())['status'] == 'instructions_unavailable'
    provider.fail = False
    monkeypatch.setattr('sys.argv', ['makeup-refine', '--retry-instructions', str(output), '--vision-model', 'vision'])
    assert cli.main() == 0
    assert json.loads((output / 'result.json').read_text())['status'] == 'completed'
    assert (output / 'originalImage.png').read_bytes() == original_bytes
    assert (output / 'enhancedImage.png').read_bytes() == enhanced_bytes
    assert [c[0] for c in provider.calls] == ['plan', 'enhance', 'explain', 'explain']


def test_cli_crops_clear_screenshot_frame_before_model_calls(tmp_path, image, monkeypatch):
    from makeup_refine import cli
    import makeup_refine.providers
    import makeup_refine.landmarks
    photo = tmp_path / 'screenshot.png'
    framed = Image.new('RGB', (image.width, image.height + 300), 'black')
    framed.paste(image, (0, 150))
    framed.save(photo)
    provider = Provider()
    provider.close = lambda: None
    original_plan = provider.plan_techniques
    def checked_plan(photo, style, points):
        assert photo.size == image.size
        return original_plan(photo, style, points)
    provider.plan_techniques = checked_plan
    detector = Detector()
    detector.close = lambda: None
    monkeypatch.setattr(makeup_refine.providers, 'OpenAIProvider', lambda *args: provider)
    monkeypatch.setattr(makeup_refine.landmarks, 'MediaPipeLandmarks', lambda *args: detector)
    monkeypatch.setattr(cli, 'get_api_key', lambda: 'test-only')
    output = tmp_path / 'result'
    monkeypatch.setattr('sys.argv', ['makeup-refine', str(photo), '--output', str(output),
                                  '--landmark-model', 'unused', '--vision-model', 'vision', '--edit-model', 'edit'])
    assert cli.main() == 0
    with Image.open(output / 'originalImage.png') as working:
        assert working.size == image.size
    with Image.open(output / 'uploadedImage.png') as source:
        assert source.size == framed.size
    report = json.loads((output / 'result.json').read_text())
    assert report['inputCrop']['cropBox'] == [0, 150, image.width, image.height + 150]
    assert report['inputCrop']['reasons'] == ['paired_black_letterbox']
    assert provider.calls[0][0] == 'plan'


def test_missing_lips_is_rejected_instead_of_silently_accepted(image):
    incomplete = [a for a in assessments([step()]) if a['area'] != 'lips']
    with pytest.raises(ValidationError):
        LookComparison(assessments=incomplete, preservationIssues=[])
    provider = Provider()
    provider.explain_changes = lambda *args: dict(assessments=incomplete, preservationIssues=[])
    result = LookPipeline(provider, provider, None).explain(
        image, provider.enhance(image, MakeupStyle.AUTO, Image.new('L', image.size, 255)))
    assert result['status'] == 'instructions_unavailable'
    assert result['steps'] == []


def test_explicit_unchanged_or_uncertain_lips_never_force_a_lip_step():
    for change in ('unchanged', 'uncertain'):
        data = assessments([])
        lip = next(a for a in data if a['area'] == 'lips')
        lip['change'] = change
        result = LookComparison(assessments=data, preservationIssues=[])
        assert result.visible_steps() == []
        lip['instruction'] = 'Invented lipstick step'
        with pytest.raises(ValidationError):
            LookComparison(assessments=data, preservationIssues=[])


def test_duplicate_area_cannot_replace_missing_lips():
    data = assessments([])
    data[5] = data[0].copy()
    with pytest.raises(ValidationError):
        LookComparison(assessments=data, preservationIssues=[])


def test_recompose_uses_no_editor_or_explainer_and_clears_old_guidance(image):
    provider = Provider()
    enhanced, result = LookPipeline(provider, provider, Detector()).recompose(image, image.copy())
    assert not provider.calls
    assert np.array_equal(enhanced, image)
    assert result['imageEditCalls'] == result['comparisonCalls'] == 0
    assert result['steps'] == [] and result['comparisonStatus'] == 'pending_new_comparison'
    assert result['legacyFullStyleMaskFallback'] is True
    assert result['lipBlendQuality']['qualityPassed']


def test_recompose_uses_saved_selected_mask_and_only_selected_lip_transfer(image):
    from makeup_refine.look_mask import direct_edit_mask
    provider = Provider()
    selected = [{'technique_id': 'eyeliner_05', 'region': 'eyeliner'}]
    enhanced, result = LookPipeline(provider, provider, Detector()).recompose(
        image, image.copy(), MakeupStyle.WORK, selected)
    points = Detector().detect(image)[0]
    expected = direct_edit_mask(image.size, points, MakeupStyle.WORK, selected)
    assert np.array_equal(np.asarray(enhanced), np.asarray(image))
    assert result['legacyFullStyleMaskFallback'] is False
    assert result['maskCoverageFraction'] == pytest.approx(
        float(np.mean(np.asarray(expected) > 0)))
    assert result['faceBaseCoverageFraction'] == 0
    assert result['lipTransferMode'] == 'unchanged'
    assert result['alignment']


def test_unplanned_global_edit_is_locked_to_original_outside_makeup_mask(image):
    provider = Provider()
    composites = []
    def edit(original, style, mask, plan):
        provider.mask = mask
        return Image.new('RGB', original.size, (0, 0, 0))
    provider.enhance = edit
    pipeline = LookPipeline(provider, provider, Detector(),
                             max_edit_attempts=1, on_aligned=composites.append)
    with pytest.raises(SpikeError, match='allowed visible-change band'):
        pipeline.run(image)
    enhanced = composites[0]
    assert np.array_equal(np.asarray(enhanced), np.asarray(image)) is False
    outside = np.asarray(provider.mask) == 0
    assert np.array_equal(np.asarray(enhanced)[outside], np.asarray(image)[outside])
    assert [call[0] for call in provider.calls] == ['plan']


@pytest.mark.parametrize('recovers', [True, False])
def test_corrective_retry_uses_original_and_same_plan_once(image, recovers):
    provider = Provider()
    calls, saved, attempts = [], [], []
    def edit(original, style, mask, plan, correction=None):
        calls.append((original, plan, correction))
        if recovers and len(calls) == 2:
            recovered = original.copy()
            recovered.paste((180, 80, 90), (200, 320, 300, 350))
            return recovered
        return Image.new('RGB', (original.width - 1, original.height), (0, 0, 0))
    provider.enhance = edit
    pipeline = LookPipeline(provider, provider, Detector(), saved.append,
                            on_attempt=attempts.append)
    if recovers:
        _, report = pipeline.run(image)
        assert report['imageEditCalls'] == 2
        assert len(saved) == 1
    else:
        with pytest.raises(SpikeError) as error:
            pipeline.run(image)
        assert error.value.details['imageEditCalls'] == 2
        assert not saved
    assert len(calls) == len(attempts) == 2
    assert all(call[0] is image for call in calls)
    assert calls[0][1] is calls[1][1]
    assert calls[0][2] is None
    assert 'image dimensions' in calls[1][2]


def test_direct_check_accepts_only_local_edits():
    original = Image.new('RGB', (100, 100), (100, 100, 100))
    mask = Image.new('L', original.size, 0)
    edited = original.copy()
    for y in range(20, 40):
        for x in range(20, 40):
            mask.putpixel((x, y), 255)
            edited.putpixel((x, y), (180, 90, 90))
    assert validate_protected_pixels(original, edited, mask)['protectedMeanPixelDelta'] == 0
    edited.putpixel((80, 80), (0, 0, 0))
    # One isolated noisy pixel is not treated as a global face rewrite.
    assert validate_protected_pixels(original, edited, mask)['protectedFractionAbove8'] < .10
    altered = Image.new('RGB', original.size, (80, 80, 80))
    with pytest.raises(SpikeError, match='outside the selected makeup regions'):
        validate_protected_pixels(original, altered, mask)


def test_protected_gate_allows_calibrated_base_makeup_variation_but_rejects_scene_repaint():
    original = Image.new('RGB', (100, 100), (100, 100, 100))
    mask = Image.new('L', original.size, 0)
    mask.paste(255, (20, 20, 80, 80))
    edited = original.copy()
    pixels = np.full((100, 100, 3), 105, dtype=np.uint8)
    pixels[20:80, 20:80] = (130, 125, 120)
    edited = Image.fromarray(pixels)
    # A moderate provider-side tone shift outside a permitted base region is
    # tolerated by the calibrated gate and still goes through visual review.
    assert validate_protected_pixels(original, edited, mask)['protectedPixelThresholds'] == {
        'maxMeanDelta': 6.0, 'maxFractionAbove8': .25}
    scene = Image.new('RGB', original.size, (115, 115, 115))
    with pytest.raises(SpikeError, match='fraction above 8'):
        validate_protected_pixels(original, scene, mask)


def test_facial_proportions_reject_eye_reshaping():
    original = Image.new('RGB', (100, 100), (100, 100, 100))
    candidate = Image.new('RGB', (100, 100), (200, 100, 100))

    class ProportionDetector(Detector):
        def detect(self, image):
            points = np.asarray(super().detect(image)[0], dtype=float)
            if image.getpixel((0, 0))[0] == 200:
                for upper, lower in zip(
                        ((33, 246, 161, 160, 159, 158, 157, 173, 133),
                         (263, 466, 388, 387, 386, 385, 384, 398, 362)),
                        ((33, 7, 163, 144, 145, 153, 154, 155, 133),
                         (263, 249, 390, 373, 374, 380, 381, 382, 362))):
                    points[list(upper), 1] -= .02
                    points[list(lower), 1] += .02
            return [points.tolist()]

    with pytest.raises(SpikeError, match='facial feature proportions'):
        validate_facial_proportions(candidate, original, ProportionDetector())


def test_facial_proportions_reject_eye_opening_decrease(monkeypatch):
    from makeup_refine import quality

    before = {'leftEyeOpeningPixels': .20, 'rightEyeOpeningPixels': .20,
              'noseWidthPixels': .50, 'mouthWidthPixels': .60}
    after = {'leftEyeOpeningPixels': .20, 'rightEyeOpeningPixels': .198,
             'noseWidthPixels': .50, 'mouthWidthPixels': .60}
    values = iter((before, after))
    monkeypatch.setattr(quality, 'paired_facial_metrics',
                        lambda original, candidate, detector: (before, after, {}))

    with pytest.raises(SpikeError, match='eye opening must not decrease'):
        quality.validate_facial_proportions(object(), object(), object())


def test_edge_safe_composite_restores_protected_pixels_without_a_hard_seam():
    original = Image.new('RGB', (100, 100), (100, 110, 120))
    edited = Image.new('RGB', (100, 100), (180, 70, 80))
    mask = Image.new('L', (100, 100), 0)
    mask.paste(255, (30, 30, 70, 70))
    result, report = edge_safe_composite(original, edited, mask)
    assert report['protectedPixelsRestoredExactly']
    assert result.getpixel((0, 0)) == original.getpixel((0, 0))
    assert result.getpixel((50, 50)) != original.getpixel((50, 50))


def test_edge_safe_composite_does_not_fade_a_full_makeup_core():
    original = Image.new('RGB', (100, 100), (100, 100, 100))
    edited = Image.new('RGB', (100, 100), (200, 40, 40))
    mask = Image.new('L', (100, 100), 128)
    result, _ = edge_safe_composite(original, edited, mask)
    result_delta = np.linalg.norm(np.asarray(result, dtype=float)[50, 50] - np.asarray(edited, dtype=float)[50, 50])
    old_delta = np.linalg.norm(np.asarray(original, dtype=float)[50, 50] - np.asarray(edited, dtype=float)[50, 50])
    assert result_delta < old_delta * .55


def test_complexion_texture_restoration_keeps_fine_detail_inside_foundation_mask():
    pixels = np.full((80, 80, 3), 120, dtype=np.uint8)
    pixels[20:60, 20:60] += (np.indices((40, 40))[0] % 3)[..., None].astype(np.uint8) * 12
    original = Image.fromarray(pixels)
    candidate = Image.fromarray(np.full((80, 80, 3), 135, dtype=np.uint8))
    mask = Image.new('L', original.size, 0)
    mask.paste(255, (20, 20, 60, 60))
    restored, report = preserve_complexion_texture(original, candidate, mask)
    assert report['textureRestorationApplied']
    assert report['textureEnergyRatio'] >= report['minimumTextureEnergyRatio'] * .95
    assert restored.getpixel((25, 25)) != restored.getpixel((25, 26))


def test_recompose_cli_is_local_and_does_not_reuse_steps(tmp_path, image, monkeypatch):
    from makeup_refine import recompose_cli
    source, output = tmp_path / 'saved', tmp_path / 'new'
    source.mkdir()
    image.save(source / 'originalImage.png')
    image.save(source / 'candidateImage.png')
    (source / 'result.json').write_text(json.dumps({'requestedStyle': 'Auto', 'steps': [step()]}))
    detector = Detector()
    detector.close = lambda: None
    monkeypatch.setattr(recompose_cli, 'MediaPipeLandmarks', lambda *args: detector)
    monkeypatch.setattr('sys.argv', ['makeup-recompose', str(source), '--output', str(output),
                                   '--landmark-model', 'unused'])
    assert recompose_cli.main() == 0
    result = json.loads((output / 'result.json').read_text())
    assert result['steps'] == [] and result['imageEditCalls'] == result['comparisonCalls'] == 0
    assert result['legacyFullStyleMaskFallback'] is True
    assert (output / 'enhancedImage.png').exists() and (output / 'review.html').exists()
    assert json.loads((source / 'result.json').read_text())['steps'] == [step()]


@pytest.mark.parametrize('issue', ['mouth_state', 'teeth_visibility'])
def test_mouth_preservation_issue_rejects_result(image, issue):
    provider = Provider(issues=[issue])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert result['status'] == 'rejected'
    assert result['steps'] == []
    assert issue in result['preservationIssues']

def test_mouth_state_constraints_in_generation_and_comparison_prompts():
    from makeup_refine.look_prompts import enhancement_prompt, comparison_prompt
    prompt = enhancement_prompt(MakeupStyle.AUTO)
    assert 'NEVER part the lips' in prompt
    assert 'keep those teeth visible' in prompt
    comparison = comparison_prompt()
    assert 'originally visible teeth disappear' in comparison
    assert 'mouth_state' in comparison and 'teeth_visibility' in comparison



def test_input_detail_rejection_stops_before_any_paid_call(image, monkeypatch):
    from makeup_refine import preflight
    from makeup_refine.look_view import look_steps_html
    diagnostics = {'rejected': True, 'regions': [], 'thresholdsCalibrated': False}
    monkeypatch.setattr(preflight, 'face_detail_metrics', lambda *args: diagnostics)
    provider = Provider()
    with pytest.raises(SpikeError) as failure:
        LookPipeline(provider, provider, Detector()).run(image)
    assert failure.value.code == 'IMAGE_BLURRY'
    assert provider.calls == []
    assert failure.value.details['inputRejected'] is True
    assert failure.value.details['retryAction'] == 'upload_clearer_photo'
    html = look_steps_html({'status': 'failed', 'message': failure.value.message})
    assert '请上传对焦清晰' in html
