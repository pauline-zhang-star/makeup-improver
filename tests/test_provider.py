import base64
from io import BytesIO
import httpx
import numpy as np
from PIL import Image
import pytest
from makeup_refine.providers import OpenAIProvider, png
from makeup_refine.models import SpikeError
from test_pipeline import plan


def test_edit_request_mask_polarity_and_retry_prompt():
    bodies = []
    original = Image.new("RGB", (512, 512), "gray")
    mask = Image.new("L", original.size, 0)
    mask.putpixel((10, 10), 255)
    mask.putpixel((11, 10), 80)
    def handler(request):
        bodies.append(request.content)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png(original)).decode()}]})
    provider = OpenAIProvider("test-key", "vision", "edit")
    provider.client.close()
    provider.client = httpx.Client(base_url="https://api.openai.com/v1/", transport=httpx.MockTransport(handler))
    try:
        provider.edit(original, mask, plan(), 0)
        provider.edit(original, mask, plan(), 1)
    finally:
        provider.close()
    assert b"Retry:" not in bodies[0] and b"Retry:" in bodies[1]
    prompt = bodies[0].split(b'name="prompt"')[1].split(b'\r\n\r\n', 1)[1].split(b'\r\n--')[0].decode()
    assert "full-strength" in prompt
    assert "subtle" not in prompt.lower() and "small" not in prompt.lower()
    mask_data = bodies[0].split(b'filename="mask.png"')[1].split(b'\r\n\r\n', 1)[1].split(b'\r\n--')[0]
    decoded = Image.open(BytesIO(mask_data))
    assert decoded.getpixel((10, 10))[3] == 0
    assert decoded.getpixel((11, 10))[3] == 0
    assert decoded.getpixel((0, 0))[3] == 255


def test_provider_error_is_sanitized():
    provider = OpenAIProvider("test-key", "vision", "edit")
    provider.client.close()
    provider.client = httpx.Client(base_url="https://api.openai.com/v1/", transport=httpx.MockTransport(
        lambda request: httpx.Response(401, json={"secret": "raw provider message"})))
    try:
        with pytest.raises(SpikeError) as error:
            provider.analyze_and_plan(Image.new("RGB", (512, 512)))
        assert error.value.code == "ANALYSIS_FAILED"
        assert "raw provider" not in str(error.value)
    finally:
        provider.close()
