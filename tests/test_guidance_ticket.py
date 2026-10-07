import pytest
from makeup_refine.guidance_ticket import issue, verify


def test_ticket_binds_owner_exact_pair_and_expiry():
    ticket = issue(b'secret', 'visitor', 'a' * 32,
                   {'flow': 'image_first', 'apiKey': 'never-copy', 'comparisonEvidence': {'regions': []}},
                   'original', 'enhanced', now=100)
    payload = verify(b'secret', 'visitor', ticket, 'original', 'enhanced', now=200)
    assert 'apiKey' not in payload['report']
    assert payload['report']['comparisonEvidence'] == {'regions': []}
    for owner, before, after, instant in [('other', 'original', 'enhanced', 200),
        ('visitor', 'altered', 'enhanced', 200), ('visitor', 'original', 'altered', 200),
        ('visitor', 'original', 'enhanced', 3800)]:
        with pytest.raises(ValueError):
            verify(b'secret', owner, ticket, before, after, now=instant)
    with pytest.raises(ValueError):
        verify(b'wrong', 'visitor', ticket, 'original', 'enhanced', now=200)


def test_downscaled_display_pair_preserves_crop_alignment_without_mutating_source():
    from makeup_refine.guidance_ticket import evidence_for_display
    evidence = {'imageSize': [1200, 1600], 'regions': [{'cropBoxes': [[120, 160, 600, 800]],
                                                    'meanPixelDelta': 4.2}]}
    scaled = evidence_for_display(evidence, (600, 800))
    assert scaled['regions'][0]['cropBoxes'] == [[60, 80, 300, 400]]
    assert scaled['pixelMetricsSourceSize'] == [1200, 1600]
    assert evidence['regions'][0]['cropBoxes'] == [[120, 160, 600, 800]]
