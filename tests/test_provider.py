import json
import httpx
from PIL import Image
import pytest
from makeup_refine.providers import OpenAIProvider
from makeup_refine.models import SpikeError
from makeup_refine.look_models import MakeupStyle


def test_provider_error_is_sanitized():
    provider = OpenAIProvider("test-key", "vision", "edit")
    provider.client.close()
    provider.client = httpx.Client(base_url="https://api.openai.com/v1/", transport=httpx.MockTransport(
        lambda request: httpx.Response(401, json={"secret": "raw provider message"})))
    try:
        with pytest.raises(SpikeError) as error:
            provider.plan_techniques(Image.new("RGB", (512, 512)), MakeupStyle.AUTO, None)
        assert error.value.code == "ANALYSIS_FAILED"
        assert "raw provider" not in str(error.value)
    finally:
        provider.close()


def test_planning_validation_failure_reports_fields_without_model_text():
    provider = OpenAIProvider('test-key', 'gpt-4.1-mini', 'gpt-image-2')
    provider.client.close()
    provider.client = httpx.Client(base_url='https://api.openai.com/v1/',
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            'choices': [{'message': {'content': json.dumps({'look_direction': 'private marker'})},
                         'finish_reason': 'stop'}]})))
    try:
        with pytest.raises(SpikeError) as error:
            provider.plan_techniques(Image.new('RGB', (64, 64)), MakeupStyle.AUTO, None)
    finally:
        provider.close()
    assert error.value.code == 'ANALYSIS_FAILED'
    failure = error.value.details['planningFailure']
    assert failure['phase'] == 'model_schema'
    assert {issue['field'] for issue in failure['issues']} >= {'region_decisions', 'visibility'}
    assert 'private marker' not in json.dumps(error.value.details)
