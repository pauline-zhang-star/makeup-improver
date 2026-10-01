import base64
import hashlib
import json
from io import BytesIO

import httpx
import pytest
from PIL import Image

from makeup_refine.cli import save_review
from makeup_refine.models import SpikeError
from makeup_refine.providers import png
from makeup_refine.trial_trace import TrialTrace, trace_for_report
from test_api_usage import provider_with, IMAGE


def test_actual_payload_and_invalid_size_image_survive(tmp_path):
    raw = png(Image.new('RGB', (64, 64), 'red'))
    provider = provider_with(lambda r: httpx.Response(200, json={'usage': IMAGE,
        'data': [{'b64_json': base64.b64encode(raw).decode()}]}))
    provider.trial_trace = TrialTrace(tmp_path)
    original = Image.new('RGB', (768, 1024), 'gray')
    try:
        with pytest.raises(SpikeError):
            provider.enhance(original, mask=Image.new('L', original.size, 255))
    finally:
        provider.close()
    calls = trace_for_report(tmp_path)
    request = calls[0]['requestPayload']
    assert request['data']['quality'] == 'medium'
    assert request['data']['prompt']
    sent_image = request['files']['image'][1]
    assert (tmp_path / sent_image['file']).read_bytes() == png(original)
    assert sent_image['sha256'] == hashlib.sha256(png(original)).hexdigest()
    assert 'Authorization' not in json.dumps(calls)
    assert 'test-secret' not in json.dumps(calls)
    save_review(tmp_path, original, None, {'status': 'failed', 'steps': [],
        'message': 'The provider changed dimensions.',
        'generationAttempts': [{'attempt': 1, 'status': 'rejected'}]})
    html = (tmp_path / 'review.html').read_text()
    assert 'data-comparison' in html and 'Rejected candidate' in html
    assert 'The provider changed dimensions.' in html
    assert (tmp_path / 'candidate-1.png').exists()
    assert '实际发送内容' in html and '实际输入图片' in html


def test_visual_rejection_and_all_attempts_keep_independent_sliders(tmp_path):
    original = Image.new('RGB', (64, 64), 'gray')
    final = Image.new('RGB', (64, 64), 'pink')
    for index, color in ((1, 'red'), (2, 'blue')):
        Image.new('RGB', original.size, color).save(tmp_path / f'candidate-{index}.png')
    save_review(tmp_path, original, final, {'status': 'rejected', 'steps': [],
        'preservationIssues': ['hair'], 'techniquePlan': None,
        'generationAttempts': [{'attempt': 1, 'status': 'rejected', 'message': 'eye shrank'},
                               {'attempt': 2, 'status': 'passed'}]})
    html = (tmp_path / 'review.html').read_text()
    assert html.count('<section data-comparison>') == 3
    assert "querySelectorAll('[data-comparison]')" in html
    assert 'pointerdown' in html and 'setPointerCapture' in html and 'pointermove' in html
    assert 'eye shrank' in html and 'hair' in html
    assert html.count('id="position"') == 1


def test_trace_preserves_retries_and_transport_failure(tmp_path):
    def fail(request):
        raise httpx.ReadTimeout('do not persist headers', request=request)
    provider = provider_with(fail)
    provider.trial_trace = TrialTrace(tmp_path)
    try:
        with pytest.raises(SpikeError):
            provider.explain_changes(Image.new('RGB', (20, 20)), Image.new('RGB', (20, 20)))
    finally:
        provider.close()
    trace = TrialTrace(tmp_path)
    assert len(trace.calls) == 1
    assert trace.calls[0]['status'] == 'transport_error'
    assert trace_for_report(tmp_path)[0]['responsePayload'] is None


def test_validation_audit_preserves_rejected_proposal_evidence():
    from test_model_planning import design, proposal
    from makeup_refine.model_planning import validate_design
    plan = validate_design(design([proposal(intensity=.9), proposal()]))
    failed, passed = plan.validation_results
    assert failed['firstFailure'] == 'invalid_or_excessive_strength'
    assert failed['proposal']['observation']
    assert failed['proposal']['intensity'] == .9
    assert passed['status'] == 'passed'
    assert passed['validatedStrength']['intensity'] == .4


def test_quality_failure_records_skipped_checks(monkeypatch):
    from test_look_flow import Provider
    from test_pipeline import Detector
    from makeup_refine.look_pipeline import LookPipeline
    import numpy as np
    original = Image.fromarray(np.random.default_rng(7).integers(40, 180, (512, 512, 3), dtype=np.uint8))
    provider = Provider()
    def fail(*args):
        raise SpikeError('QUALITY_CHECK_FAILED', 'Eye geometry moved.')
    monkeypatch.setattr('makeup_refine.look_pipeline.validate_candidate_geometry', fail)
    attempts = []
    with pytest.raises(SpikeError):
        LookPipeline(provider, provider, Detector(), max_edit_attempts=1,
                     on_attempt=attempts.append).run(original)
    assert attempts[0]['checks']['landmark_geometry']['status'] == 'failed'
    assert attempts[0]['checks']['protected_pixels']['status'] == 'not_run'
    assert attempts[0]['checks']['generation']['status'] == 'passed'
