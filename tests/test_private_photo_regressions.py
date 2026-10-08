"""Optional local photo regression suite. Public CI uses the procedural matrix."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from makeup_refine.look_mask import lip_pigment_mask, mouth_interior_mask
from makeup_refine.imaging import edge_safe_composite

ROOT = Path(__file__).resolve().parents[1] / 'private-fixtures/photo-regression'
MANIFEST = ROOT / 'manifest.json'
CASES = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []


@pytest.mark.parametrize('case', CASES, ids=[c['id'] for c in CASES])
def test_saved_photo_lip_contact_and_mouth_interior(case):
    path = ROOT / case['image']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == case['sha256']
    image = Image.open(path).convert('RGB')
    points = np.asarray(case['points'])
    mask = lip_pigment_mask(image.size, points)
    mouth = np.asarray(mouth_interior_mask(image.size, points)) > 0
    # A conspicuous synthetic pigment exposes any accidental original-color stripe.
    color = (175, 45, 70)
    candidate = Image.new('RGB', image.size, color)
    final, _ = edge_safe_composite(image, candidate, mask, pigment_mask=mask)
    before, after = np.asarray(image), np.asarray(final)
    outside = np.asarray(mask) == 0
    assert np.array_equal(after[outside], before[outside])
    if case['mouthState'] == 'closed':
        assert not mouth.any()
        x,y = np.rint((points[13]+points[14])/2*np.asarray(image.size)).astype(int)
        assert max(abs(a-b) for a,b in zip(final.getpixel((x,y)), color)) <= 2
    else:
        assert mouth.any()
        assert np.array_equal(after[mouth], before[mouth])
