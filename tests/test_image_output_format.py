import base64
from io import BytesIO
import httpx
import numpy as np
import pytest
from PIL import Image
from makeup_refine.models import SpikeError
from makeup_refine.providers import OpenAIProvider


@pytest.mark.parametrize('fmt', ['png','jpeg','webp'])
def test_requested_format_preserves_canvas_and_mask_and_decodes(fmt,monkeypatch):
    monkeypatch.setenv('MAKEUP_EDIT_OUTPUT_FORMAT',fmt)
    original=Image.new('RGB',(768,1024),(100,110,120))
    mask=Image.new('L',original.size,255)
    output=BytesIO();original.save(output,format=fmt.upper(),**({'quality':100} if fmt!='png' else {}))
    requests=[]
    def handle(request):
        requests.append(request)
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(output.getvalue()).decode()}]})
    provider=OpenAIProvider('test','vision','gpt-image-2')
    provider.client.close();provider.client=httpx.Client(base_url='https://api.openai.com/v1/',transport=httpx.MockTransport(handle))
    try:
        result=provider.enhance(original,mask=mask)
    finally:
        provider.close()
    assert result.size==original.size
    body=requests[0].content
    assert b'name="size"\r\n\r\n768x1024' in body
    assert b'name="quality"\r\n\r\nlow' in body
    assert ('name="output_format"\r\n\r\n'+fmt).encode() in body
    assert b'filename="mask.png"' in body and b'filename="selfie.png"' in body
    if fmt=='png':
        assert b'name="output_compression"' not in body
        assert np.array_equal(result,original)
    else:
        assert b'name="output_compression"\r\n\r\n100' in body


def test_invalid_output_format_fails_before_network(monkeypatch):
    monkeypatch.setenv('MAKEUP_EDIT_OUTPUT_FORMAT','invalid')
    with pytest.raises(SpikeError,match='Invalid image output format'):
        OpenAIProvider('test','vision','gpt-image-2')


def test_region_generation_pastes_at_original_coordinates_and_keeps_native_pixels(monkeypatch):
    from PIL import ImageDraw
    from makeup_refine.imaging import edit_region_box
    monkeypatch.setenv('MAKEUP_EDIT_CANVAS_MODE','region')
    monkeypatch.setenv('MAKEUP_EDIT_OUTPUT_FORMAT','png')
    original=Image.fromarray(np.random.default_rng(9).integers(0,255,(1536,1152,3),dtype=np.uint8))
    mask=Image.new('L',original.size,0);ImageDraw.Draw(mask).rectangle((295,564,881,1106),fill=255)
    box=edit_region_box(original,mask)
    candidate=original.crop(box);ImageDraw.Draw(candidate).rectangle((120,137,130,147),fill=(200,40,40))
    output=BytesIO();candidate.save(output,format='PNG')
    requests=[]
    def handle(request):
        requests.append(request)
        return httpx.Response(200,json={'data':[{'b64_json':base64.b64encode(output.getvalue()).decode()}]})
    provider=OpenAIProvider('test','vision','gpt-image-2');provider.client.close()
    provider.client=httpx.Client(base_url='https://api.openai.com/v1/',transport=httpx.MockTransport(handle))
    try:result=provider.enhance(original,mask=mask)
    finally:provider.close()
    expected=original.copy();expected.paste(candidate,box[:2])
    assert result.size==original.size and np.array_equal(result,expected)
    assert b'name="size"\r\n\r\n816x816' in requests[0].content
    record=provider.usage_ledger.calls[0]
    assert record['imageSettings']['size']=='816x816'
    assert record['inputImageBytes']>0 and record['responseBytes']>0


def test_low_quality_is_explicit_and_default_is_low(monkeypatch):
    monkeypatch.delenv('MAKEUP_EDIT_QUALITY',raising=False)
    provider=OpenAIProvider('test','vision','gpt-image-2')
    assert provider.edit_quality=='low'
    provider.close()
    monkeypatch.setenv('MAKEUP_EDIT_QUALITY','low')
    provider=OpenAIProvider('test','vision','gpt-image-2')
    assert provider.edit_quality=='low'
    provider.close()
    monkeypatch.setenv('MAKEUP_EDIT_QUALITY','invalid')
    with pytest.raises(SpikeError,match='Invalid image generation quality'):
        OpenAIProvider('test','vision','gpt-image-2')
