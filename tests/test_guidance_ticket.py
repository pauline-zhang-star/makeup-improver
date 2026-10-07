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
