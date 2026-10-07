import json
import numpy as np
import pytest
from PIL import Image, ImageDraw
from makeup_refine.imaging import outer_envelope
from makeup_refine.fast_ai import (planning_contract, planning_decode, comparison_contract,
                                   comparison_decode, detail_boards)
from makeup_refine.model_planning import validate_design
from makeup_refine.look_models import LOOK_AREAS


def test_run_filling_matches_original_four_connected_corner_fill():
    random = np.random.default_rng(17)
    cases = [random.random((31, 47)) > density for density in (.1, .4, .7, .95)]
    ring = np.zeros((80, 100), dtype=bool)
    ring[20:60, 20:80] = True
    ring[30:50, 30:70] = False
    cases += [ring, np.zeros_like(ring), np.ones_like(ring)]
    for support in cases:
        inverted = Image.fromarray(np.uint8(~support) * 255).copy()
        if not support[0, 0]:
            ImageDraw.floodfill(inverted, (0, 0), 0)
        assert np.array_equal(outer_envelope(support), support | (np.asarray(inverted) > 0))


def test_compact_planner_preserves_executable_parameters_and_evidence():
    from test_model_planning import design, proposal
    source = design([proposal()])
    entry = source['region_decisions'][0]
    for key in ('observation', 'style_reason'):
        entry[key] = entry['structured_evidence'][key]
    canonical = validate_design(source)
    for key in ('observation', 'style_reason', 'application_zh'):
        entry.pop(key, None)
    restored = validate_design(planning_decode(json.dumps(source)))
    assert restored.model_dump() == canonical.model_dump()
    prompt, response = planning_contract('Auto')
    assert '"$defs"' not in prompt
    props = response['json_schema']['schema']['$defs']['PlacementTechnique']['properties']
    assert 'application_zh' not in props and 'structured_evidence' in props
    entry['observation'] = 'Unexpected duplicate'
    with pytest.raises(ValueError):
        planning_decode(json.dumps(source))


def test_compact_review_requires_all_areas_and_bilingual_real_instructions():
    rows = [dict(a=area,c='unchanged',p=.95,b='No change',t='No change',i=None,z=None) for area in LOOK_AREAS]
    rows[-1].update(c='changed',i='Blend sheer foundation on uneven cheek tone.',z='在脸颊肤色不均处薄涂粉底并晕开。')
    value = dict(p=[],a=rows)
    review = comparison_decode(json.dumps(value))
    assert len(review.assessments) == 8
    assert review.visible_steps()[0].instruction_zh == rows[-1]['z']
    rows.pop()
    with pytest.raises(ValueError):
        comparison_decode(json.dumps(value))
    prompt, contract = comparison_contract()
    assert '"$defs"' not in prompt
    assert contract['json_schema']['strict']
    assert 'mouth_state' in prompt and 'makeup_artifacts' in prompt


def test_boards_keep_every_unique_pair_and_original_crop_pixels():
    original = Image.new('RGB', (200, 200), (10, 20, 30))
    enhanced = Image.new('RGB', original.size, (40, 50, 60))
    box = [20, 30, 100, 120]
    evidence = {'regions': [{'area':'blush','cropBoxes':[box, box]}]}
    boards = list(detail_boards(original, enhanced, evidence))
    assert len(boards) == 1
    board = boards[0]
    assert np.array_equal(board.crop((0,36,80,126)), original.crop(box))
    assert np.array_equal(board.crop((board.width//2,36,board.width//2+80,126)), enhanced.crop(box))


def test_provider_fast_path_uses_compact_schema_and_complete_images(monkeypatch):
    import httpx
    from makeup_refine.providers import OpenAIProvider
    monkeypatch.setenv('MAKEUP_FAST_AI', '1')
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        rows = [dict(a=area,c='unchanged',p=.95,b='Same visible makeup',t='Same visible makeup',i=None,z=None) for area in LOOK_AREAS]
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'p':[],'a':rows})}}]})
    provider = OpenAIProvider('test','vision','unused')
    provider.client.close()
    provider.client = httpx.Client(base_url='https://api.openai.com/v1/',transport=httpx.MockTransport(handle))
    original = Image.new('RGB',(200,200),(10,20,30))
    evidence = {'regions':[{'area':'blush','cropBoxes':[[20,30,100,120],[110,30,190,120]]}]}
    try:
        comparison = provider.explain_changes(original,original,evidence)
    finally:
        provider.close()
    assert len(comparison.assessments) == 8
    payload = requests[0]
    assert payload['response_format']['type'] == 'json_schema'
    assert len([item for item in payload['messages'][1]['content'] if item['type']=='image_url']) == 3
    assert '"$defs"' not in payload['messages'][0]['content']
