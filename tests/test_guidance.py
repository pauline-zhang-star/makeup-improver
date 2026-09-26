import pytest
from PIL import Image, ImageDraw
from makeup_refine.guidance import GUIDES, guided_change, location_outlines
from makeup_refine.guidance_view import guidance_html
from makeup_refine.models import ALLOWED, Change, SpikeError


def test_all_supported_techniques_have_short_bilingual_guides():
    assert set(GUIDES) == set.union(*ALLOWED.values())
    assert all(len(en.split()) <= 12 and zh for en, zh in GUIDES.values())


def test_eye_locations_are_separate_and_preserve_details():
    mask = Image.new('L', (100, 100))
    draw = ImageDraw.Draw(mask)
    draw.rectangle((10, 20, 30, 25), fill=255)
    draw.rectangle((60, 20, 80, 25), fill=255)
    change = Change(area='eyeliner', type='lift_outer_wing', severity='subtle',
                    instruction='Detailed instruction', rationale='Reason')
    result = guided_change(change, mask, 0)
    assert result['detailInstruction'] == change.instruction
    assert result['instruction'] == GUIDES[change.type][0]
    assert len(result['annotations']) == 2
    assert result['annotations'][0]['normalizedPoints'][1][0] < .5
    assert result['annotations'][1]['normalizedPoints'][0][0] > .5


def test_empty_mask_is_rejected():
    with pytest.raises(SpikeError):
        location_outlines(Image.new('L', (10, 10)), 'lips')


def test_guide_escapes_text_and_rejects_invalid_coordinates():
    markup = guidance_html('data:image/png;base64,', [{
        'area': 'lips', 'instruction': '<script>bad()</script>',
        'annotation': {'normalizedPoints': [[0, 0], [1, 0], [float('nan'), 1]]}}])
    assert '<script>bad()' not in markup
    assert '&lt;script&gt;' in markup
    assert '<polygon' not in markup
    assert 'aria-pressed' in markup
