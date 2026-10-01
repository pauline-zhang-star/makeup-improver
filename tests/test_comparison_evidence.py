import base64
from io import BytesIO
import json

import httpx
import numpy as np
from PIL import Image

from makeup_refine.comparison_evidence import build_comparison_evidence, unresolved_evidence
from makeup_refine.look_models import LookComparison
from makeup_refine.providers import OpenAIProvider
from makeup_refine.look_view import look_steps_html
from test_look_flow import assessments


def evidence_pair(monkeypatch):
    mask = Image.new('L', (60, 40))
    for x in range(5, 55):
        for y in range(10, 25):
            mask.putpixel((x, y), 255)
    monkeypatch.setattr('makeup_refine.comparison_evidence.direct_edit_mask', lambda *args: mask)
    original = Image.new('RGB', mask.size, (120, 100, 90))
    pixels = np.array(original)
    pixels[10:25, 5:55, 0] += 12  # diffuse low-contrast blush, with no geometry shift
    enhanced = Image.fromarray(pixels)
    evidence = build_comparison_evidence(original, enhanced, [(0.5, 0.5)] * 468, 'Auto',
                                         [{'technique_id': 'blush_01', 'region': 'blush'}])
    return original, enhanced, evidence


def test_diffuse_color_detected_but_not_automatically_confirmed(monkeypatch):
    original, enhanced, evidence = evidence_pair(monkeypatch)
    region = evidence['regions'][0]
    assert region['needsCloseReview'] and region['meanPixelDelta'] == 4
    assert region['meanSignedRGBDelta'] == [12, 0, 0]
    assert len(region['cropBoxes']) == 2
    comparison = LookComparison(assessments=assessments([]), preservationIssues=[])
    pending = unresolved_evidence(evidence, comparison)
    assert [p['area'] for p in pending] == ['blush']
    assert comparison.visible_steps() == []
    assert 'blush' in look_steps_html({'status': 'completed', 'steps': [], 'pendingChangeReviews': pending})


def test_unchanged_pair_has_no_numeric_attention(monkeypatch):
    original, _, _ = evidence_pair(monkeypatch)
    evidence = build_comparison_evidence(original, original, [(0.5, 0.5)] * 468, 'Auto',
                                         [{'technique_id': 'blush_01', 'region': 'blush'}])
    assert evidence['regions'][0]['meanPixelDelta'] == 0
    assert not evidence['regions'][0]['needsCloseReview']
    comparison = LookComparison(assessments=assessments([]), preservationIssues=[])
    assert not unresolved_evidence(evidence, comparison)


def test_provider_sends_actual_matched_crops_and_metrics(monkeypatch):
    original, enhanced, evidence = evidence_pair(monkeypatch)
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
            'assessments': assessments([]), 'preservationIssues': []})}}]})
    provider = OpenAIProvider('test', 'vision', 'unused')
    provider.client.close()
    provider.client = httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(handler))
    try:
        provider.explain_changes(original, enhanced, evidence=evidence)
    finally:
        provider.close()
    content = requests[0]['messages'][1]['content']
    assert 'meanSignedRGBDelta' in content[4]['text']
    assert len([c for c in content if c['type'] == 'image_url']) == 6
    for entry, source in ((content[6], original), (content[8], enhanced)):
        actual = Image.open(BytesIO(base64.b64decode(entry['image_url']['url'].split(',')[1])))
        expected = source.crop(tuple(evidence['regions'][0]['cropBoxes'][0]))
        expected = expected.resize(actual.size, Image.Resampling.LANCZOS)
        assert np.array_equal(actual, expected)
    assert 'requestedStyle' not in content[4]['text']


def test_pixel_visibility_gate_accepts_reduction_as_well_as_addition():
    from makeup_refine.quality import region_metrics
    lighter = Image.new('RGB', (40, 40), (140, 120, 110))
    darker = Image.new('RGB', (40, 40), (130, 110, 100))
    mask = Image.new('L', lighter.size, 255)
    reduction = region_metrics(darker, lighter, [mask])[0]
    addition = region_metrics(lighter, darker, [mask])[0]
    assert reduction == addition
    assert reduction['passesNumericBand']
