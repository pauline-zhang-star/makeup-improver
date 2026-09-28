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
from makeup_refine.quality import validate_protected_pixels
from makeup_refine.providers import OpenAIProvider, png
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

    def explain_changes(self, original, enhanced):
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
    assert enhanced.getpixel((250, 330)) == (180, 80, 90)
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
    assert 'soft everyday polish' in prompt
    assert 'brow arch' in prompt and 'bridge highlight' in prompt
    assert 'cupid bow' in prompt and 'fuller' in prompt
    assert 'face reshaping' in prompt and 'mouth open or closed exactly' in prompt


def test_selected_style_uses_wider_mask_than_auto(image):
    _, auto = LookPipeline(Provider(), Provider(), Detector()).run(image, MakeupStyle.AUTO)
    _, selected = LookPipeline(Provider(), Provider(), Detector()).run(image, MakeupStyle.SOFT_GLAM)
    assert selected['maskCoverageFraction'] > auto['maskCoverageFraction']
    assert auto['generationMode'] == selected['generationMode'] == 'direct_api_result'


def test_unchanged_and_uncertain_areas_are_omitted(image):
    provider = Provider([step('lips'), step('eyebrows', False), step('blush', confidence=.4)])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert [s['area'] for s in result['steps']] == ['lips']


def test_only_observed_planned_areas_count_toward_three_step_goal():
    selected = [{'technique_id': 'lips_02', 'region': 'lips'},
                {'technique_id': 'eyeliner_05', 'region': 'eyeliner'},
                {'technique_id': 'blush_01', 'region': 'blush'}]
    explanation = {'steps': [step('eyeliner'), step('lashes'), step('blush'),
                             step('lips'), step('complexion')]}
    coverage = reconcile_guidance_with_plan(explanation, selected)
    assert coverage['visibleChangeCount'] == 5
    assert coverage['confirmedPlannedChangeCount'] == 3
    assert coverage['minimumVisibleChangesMet']
    assert coverage['unexpectedMakeupChanges'] == ['complexion', 'lashes']
    assert [s['area'] for s in explanation['steps']] == ['eyeliner', 'blush', 'lips']
    assert 'center of the lower lip' in explanation['steps'][-1]['instruction']


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
    assert 'Eyeliner must not enter the eye opening' in prompt


def test_identical_pair_skips_paid_comparison(image):
    provider = Provider()
    result = LookPipeline(provider, provider, Detector()).explain(image, image.copy())
    assert result['status'] == 'completed_no_visible_changes'
    assert not provider.calls


def test_observed_base_makeup_is_allowed_but_does_not_replace_planned_techniques(image):
    from makeup_refine.look_pipeline import summarize_observed_changes
    provider = Provider(steps=[step('lips'), step('complexion')])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert result['allowedSupplementaryAreas'] == ['complexion']
    assert result['observedSupplementaryChangeAreas'] == ['complexion']
    assert result['unexpectedMakeupChanges'] == []
    assert result['confirmedPlannedChangeCount'] == 1
    assert not result['minimumVisibleChangesMet']
    assert {s['area'] for s in result['steps']} == {'lips', 'complexion'}
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
    assert base_only.sum() > 50000
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
        'measurements': {
            'brow_density_gap_score': {'value': .9, 'detection_confidence': .98},
            'brow_visibility': {'value': .99, 'detection_confidence': .98},
        },
            'visibility': {region: {'value': region == 'brows', 'detection_confidence': .98}
                           for region in ('eyeliner', 'eyeshadow', 'brows', 'lips', 'blush',
                                          'nose_contour', 'foundation')},
        'lighting_gate': {'value': True, 'detection_confidence': .98},
        'proposals': [{'technique_id': 'brow_04', 'intensity': .4}],
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
    assert 'at most seven' in body['messages'][0]['content']
    assert body['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')


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
    assert result['lipBlendQuality']['qualityPassed']


def test_unplanned_global_edit_never_saves_or_explains(image):
    provider = Provider()
    saved = []
    provider.enhance = lambda original, style, mask, plan: Image.new('RGB', original.size, (0, 0, 0))
    with pytest.raises(SpikeError, match='outside the selected makeup regions'):
        LookPipeline(provider, provider, Detector(), saved.append, max_edit_attempts=1).run(image)
    assert not saved
    assert [call[0] for call in provider.calls] == ['plan']


@pytest.mark.parametrize('recovers', [True, False])
def test_corrective_retry_uses_original_and_same_plan_once(image, recovers):
    provider = Provider()
    calls, saved, attempts = [], [], []
    def edit(original, style, mask, plan, correction=None):
        calls.append((original, plan, correction))
        if recovers and len(calls) == 2:
            return original.copy()
        return Image.new('RGB', original.size, (0, 0, 0))
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
    assert 'outside the selected makeup regions' in calls[1][2]


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
    assert (output / 'enhancedImage.png').exists() and (output / 'review.html').exists()
    assert json.loads((source / 'result.json').read_text())['steps'] == [step()]
