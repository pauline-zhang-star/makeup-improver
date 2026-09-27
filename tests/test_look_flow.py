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
from makeup_refine.look_pipeline import LookPipeline
from makeup_refine.lip_blend import lip_regions, _dilate
from makeup_refine.look_prompts import enhancement_prompt
from makeup_refine.models import SpikeError
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

    def enhance(self, original, style, mask):
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
        assert [c[0] for c in provider.calls] == ['enhance']
        saved.append(enhanced)
    enhanced, result = LookPipeline(provider, provider, Detector(), save).run(image)
    assert [c[0] for c in provider.calls] == ['enhance', 'explain']
    assert provider.calls[0][1] == MakeupStyle.AUTO
    assert provider.calls[1][1] is image
    assert provider.calls[1][2] is saved[0] is enhanced
    points = Detector().detect(image)[0]
    union, _, opening, _, _ = lip_regions(image.size, points, points)
    lip_support = _dilate(union, result['lipBlendQuality']['after']['marginPixels']) & ~opening
    outside = (np.asarray(provider.mask) == 0) & ~lip_support
    assert np.array_equal(np.asarray(enhanced)[outside], np.asarray(image)[outside])
    assert result['lipTransferMode'] == 'spatial_adaptive_poisson'
    assert result['requestedStyle'] == 'Auto'
    assert result['steps'][0]['instruction'] == step()['instruction']


@pytest.mark.parametrize('style', list(MakeupStyle))
def test_styles_are_explicit_and_forwarded_without_planning(image, style):
    provider = Provider()
    _, result = LookPipeline(provider, provider, Detector()).run(image, style)
    assert provider.calls[0] == ('enhance', style)
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
    assert auto['faceBaseStrength'] == 0
    assert selected['faceBaseStrength'] == .6


def test_unchanged_and_uncertain_areas_are_omitted(image):
    provider = Provider([step('lips'), step('eyebrows', False), step('blush', confidence=.4)])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert [s['area'] for s in result['steps']] == ['lips']


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


def test_identical_pair_skips_paid_comparison(image):
    provider = Provider()
    result = LookPipeline(provider, provider, Detector()).explain(image, image.copy())
    assert result['status'] == 'completed_no_visible_changes'
    assert not provider.calls


def test_explanation_failure_keeps_image_and_retry_never_regenerates(image):
    provider = Provider(fail=True)
    enhanced, result = LookPipeline(provider, provider, Detector()).run(image)
    assert enhanced is not None and result['status'] == 'instructions_unavailable'
    provider.fail = False
    retry = LookPipeline(provider, provider, None).explain(image, enhanced)
    assert retry['status'] == 'completed'
    assert [c[0] for c in provider.calls] == ['enhance', 'explain', 'explain']


def test_preservation_issue_rejects_instructions(image):
    provider = Provider(issues=['glasses'])
    _, result = LookPipeline(provider, provider, Detector()).run(image)
    assert result['status'] == 'rejected' and result['steps'] == []


def test_dimension_failure_never_explains_or_saves(image):
    provider = Provider()
    provider.enhance = lambda original, style, mask: Image.new('RGB', (256, 256))
    saved = []
    with pytest.raises(SpikeError, match='dimensions'):
        LookPipeline(provider, provider, Detector(), saved.append).run(image)
    assert not saved and not provider.calls


def test_rejected_candidate_is_retained_before_geometry_check(image):
    provider = Provider()
    provider.enhance = lambda original, style, mask: Image.new('RGB', (256, 256))
    candidate, accepted = [], []
    with pytest.raises(SpikeError, match='dimensions'):
        LookPipeline(provider, provider, Detector(), accepted.append, candidate.append).run(image)
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


def test_small_photo_is_scaled_and_masked_for_api_without_padding():
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
    assert sent_mask.getpixel((504, 336))[3] == 0


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
    assert [c[0] for c in provider.calls] == ['enhance', 'explain', 'explain']


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


def test_lip_rejection_never_saves_or_explains_or_reverts(image, monkeypatch):
    provider = Provider()
    saved = []
    def reject(*args):
        raise SpikeError('QUALITY_CHECK_FAILED', 'Automatic lip blending failed.')
    monkeypatch.setattr('makeup_refine.look_pipeline.blend_full_lips', reject)
    with pytest.raises(SpikeError, match='Automatic lip blending failed'):
        LookPipeline(provider, provider, Detector(), saved.append).run(image)
    assert not saved
    assert [call[0] for call in provider.calls] == ['enhance']


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
