import json

import httpx
import pytest
from PIL import Image

from makeup_refine.api_usage import UsageLedger, attach_usage, estimate, safe_usage
from makeup_refine.providers import OpenAIProvider
from makeup_refine.models import SpikeError
from makeup_refine.cli import save_review
from makeup_refine.look_view import api_cost_html
from test_look_flow import assessments

CHAT = {'prompt_tokens': 1000, 'completion_tokens': 200,
        'prompt_tokens_details': {'cached_tokens': 400}}
IMAGE = {'input_tokens': 1500, 'input_tokens_details': {'text_tokens': 1000, 'image_tokens': 500},
         'output_tokens': 2000, 'total_tokens': 3500}


def provider_with(handler):
    provider = OpenAIProvider('test-secret-not-for-logs', 'gpt-4.1-mini', 'gpt-image-2')
    provider.client.close()
    provider.client = httpx.Client(base_url='https://api.openai.com/v1/', transport=httpx.MockTransport(handler))
    return provider


def test_cached_text_and_image_rates_are_distinct():
    assert estimate('gpt-4.1-mini', 'chat/completions', CHAT) == pytest.approx(.0006)
    assert estimate('gpt-image-2', 'images/edits', IMAGE) == pytest.approx(.0345)
    assert estimate('unknown-model', 'images/edits', IMAGE) is None
    assert estimate('gpt-image-2', 'images/edits', {'input_tokens': 1500, 'output_tokens': 2000}) is None
    assert estimate('gpt-4.1-mini', 'chat/completions', None) is None
    assert estimate('gpt-4.1-mini', 'chat/completions', {**CHAT, 'prompt_tokens': -1}) is None
    assert safe_usage({'prompt_tokens': 1, 'secret': 'do not save', 'completion_tokens': True}) == {'prompt_tokens': 1}


def test_rejected_api_image_still_has_cost_and_no_secrets(tmp_path):
    provider = provider_with(lambda r: httpx.Response(200, headers={'x-request-id': 'req-test'},
        json={'usage': IMAGE, 'data': [{'b64_json': 'invalid-image'}]}))
    report = {}
    attach_usage(provider, tmp_path, report)
    try:
        with pytest.raises(SpikeError):
            provider.enhance(Image.new('RGB', (768, 1024)), mask=Image.new('L', (768, 1024), 255))
        with pytest.raises(SpikeError):
            provider.enhance(Image.new('RGB', (768, 1024)), mask=Image.new('L', (768, 1024), 255))
    finally:
        provider.close()
    saved = json.loads((tmp_path / 'api-usage.json').read_text())
    assert saved['recordedCalls'] == 2
    assert saved['totalEstimatedUSD'] == pytest.approx(.069)
    assert saved['byStage']['generation']['calls'] == 2
    assert saved['calls'][0]['requestId'] == 'req-test'
    serialized = json.dumps(saved)
    assert 'test-secret' not in serialized and 'b64_json' not in serialized


@pytest.mark.parametrize('failure', ['timeout', 'http', 'missing_usage', 'bad_json'])
def test_unknown_cost_is_never_reported_as_zero(failure):
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('secret transport message', request=request)
        if failure == 'http':
            return httpx.Response(429, json={'error': 'no usage'})
        if failure == 'bad_json':
            return httpx.Response(200, text='not json')
        return httpx.Response(200, json={})
    provider = provider_with(handler)
    try:
        with pytest.raises(SpikeError):
            provider.explain_changes(Image.new('RGB', (20, 20)), Image.new('RGB', (20, 20)))
    finally:
        provider.close()
    snapshot = provider.usage_ledger.snapshot()
    assert snapshot['recordedCalls'] == snapshot['unpricedCalls'] == 1
    assert snapshot['totalEstimatedUSD'] is None and not snapshot['complete']
    assert 'secret transport message' not in json.dumps(snapshot)
    assert '总费用未知' in api_cost_html({'apiUsage': snapshot})


def test_retry_ledger_accumulates_without_repricing_or_double_count(tmp_path):
    p = provider_with(lambda r: httpx.Response(200, json={'usage': CHAT}))
    attach_usage(p, tmp_path, {}, historical=True)
    p._post('comparison', 'chat/completions', json={'model': 'gpt-4.1-mini'})
    p.usage_ledger.notify()
    p.close()
    q = provider_with(lambda r: httpx.Response(200, json={'usage': CHAT}))
    attach_usage(q, tmp_path, {}, historical=True)
    q._post('comparison', 'chat/completions', json={'model': 'gpt-4.1-mini'})
    q.close()
    saved = json.loads((tmp_path / 'api-usage.json').read_text())
    assert saved['recordedCalls'] == 2
    assert saved['knownEstimatedUSD'] == pytest.approx(.0012)
    assert saved['historicalUsageMissing'] and saved['totalEstimatedUSD'] is None
    assert len({c['id'] for c in saved['calls']}) == 2


def test_in_flight_call_survives_interruption(tmp_path):
    p = provider_with(lambda r: httpx.Response(200))
    attach_usage(p, tmp_path, {})
    p.usage_ledger.begin('planning', 'chat/completions', 'gpt-4.1-mini')
    p.close()
    saved = json.loads((tmp_path / 'api-usage.json').read_text())
    assert saved['calls'][0]['status'] == 'in_flight'
    assert saved['totalEstimatedUSD'] is None


def test_cli_retry_persists_usage_on_parse_failure_and_keeps_images(tmp_path, monkeypatch):
    from makeup_refine import cli, providers
    original = Image.new('RGB', (20, 20), 'gray')
    enhanced = Image.new('RGB', (20, 20), 'red')
    original.save(tmp_path / 'originalImage.png')
    enhanced.save(tmp_path / 'enhancedImage.png')
    save_review(tmp_path, original, enhanced, {'status': 'completed', 'steps': []})
    expected = (tmp_path / 'enhancedImage.png').read_bytes()
    def make_provider(*args):
        return provider_with(lambda r: httpx.Response(200, json={'usage': CHAT,
            'choices': [{'message': {'content': 'not valid comparison json'}}]}))
    monkeypatch.setattr(providers, 'OpenAIProvider', make_provider)
    monkeypatch.setattr(cli, 'get_api_key', lambda: 'test')
    monkeypatch.setattr('sys.argv', ['makeup-refine', '--retry-instructions', str(tmp_path),
                                   '--vision-model', 'gpt-4.1-mini'])
    assert cli.main() == 0
    assert cli.main() == 0
    report = json.loads((tmp_path / 'result.json').read_text())
    assert report['apiUsage']['recordedCalls'] == 2
    assert report['apiUsage']['knownEstimatedUSD'] == pytest.approx(.0012)
    assert report['status'] == 'instructions_unavailable'
    assert 'API 费用' in (tmp_path / 'review.html').read_text()
    assert (tmp_path / 'enhancedImage.png').read_bytes() == expected


def test_invalid_planning_content_keeps_planning_cost():
    provider = provider_with(lambda r: httpx.Response(200, json={'usage': CHAT,
        'choices': [{'message': {'content': '{}'}}]}))
    try:
        with pytest.raises(SpikeError):
            provider.plan_techniques(Image.new('RGB', (20, 20)), 'Auto', [])
    finally:
        provider.close()
    summary = provider.usage_ledger.snapshot()
    assert summary['byStage']['planning']['knownEstimatedUSD'] == pytest.approx(.0006)
    assert summary['complete']
