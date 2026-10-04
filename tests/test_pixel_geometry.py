import numpy as np
import pytest
from PIL import Image
from makeup_refine.quality import paired_facial_metrics, PROPORTION_ANCHORS, APERTURE_PAIRS


def landmarks():
    p = np.full((478, 2), .5)
    for i, t in zip(PROPORTION_ANCHORS, np.linspace(0, 2*np.pi, len(PROPORTION_ANCHORS), endpoint=False)):
        p[i] = (.5 + .3*np.cos(t), .5 + .4*np.sin(t))
    for eye, cx in zip(APERTURE_PAIRS, (.35, .65)):
        for (up, down), dx in zip(eye, (-.03, 0, .03)):
            p[up] = (cx+dx, .38); p[down] = (cx+dx, .42)
    p[98], p[327] = (.44,.55),(.56,.55)
    p[61], p[291] = (.4,.7),(.6,.7)
    p[33], p[263] = (.3,.4),(.7,.4)
    return p


def measure(before, after):
    points = iter([before.tolist(), after.tolist()])
    class Detector:
        def detect(self, image): return [next(points)]
    return paired_facial_metrics(Image.new('RGB',(800,1200),'black'),Image.new('RGB',(800,1200),'white'),Detector())


def test_external_eye_corner_movement_cannot_change_other_measurements():
    p=landmarks();q=p.copy();q[33,0]+=.04;q[263,0]-=.04
    before,after,audit=measure(p,q)
    assert after == before
    assert not audit['normalizationByEyeSpan']
    assert before['mouthWidthPixels']==pytest.approx(160)
    assert before['noseWidthPixels']==pytest.approx(96)
    assert before['leftEyeOpeningPixels']==pytest.approx(48)


def test_camera_rotation_scale_translation_removed_in_pixel_space():
    p=landmarks();pixels=p*np.array([800,1200]);theta=np.deg2rad(1)
    matrix=1.02*np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]])
    q=(pixels@matrix.T+[3,-5])/[800,1200]
    before,after,_=measure(p,q)
    for k in before: assert after[k]==pytest.approx(before[k],abs=1e-9)


def test_actual_local_eye_closure_and_mouth_widening_remain_measurable():
    p=landmarks();q=p.copy()
    for up,down in APERTURE_PAIRS[0]: q[up,1]+=.005;q[down,1]-=.005
    q[61,0]-=.01;q[291,0]+=.01
    before,after,_=measure(p,q)
    assert after['leftEyeOpeningPixels']==pytest.approx(before['leftEyeOpeningPixels']-12)
    assert after['rightEyeOpeningPixels']==pytest.approx(before['rightEyeOpeningPixels'])
    assert after['mouthWidthPixels']==pytest.approx(before['mouthWidthPixels']+16)
    assert after['noseWidthPixels']==pytest.approx(before['noseWidthPixels'])


def test_identical_feature_pixels_override_detector_drift():
    p=landmarks();q=p.copy();q[98,0]-=.02;q[327,0]+=.02
    points=iter([p.tolist(),q.tolist()])
    class Detector:
        def detect(self,image): return [next(points)]
    image=Image.new('RGB',(800,1200),'gray')
    before,after,audit=paired_facial_metrics(image,image.copy(),Detector())
    assert after['noseWidthPixels']==before['noseWidthPixels']
    assert audit['rawMeasuredAfterPixels']['noseWidthPixels']>before['noseWidthPixels']
    assert audit['localPixelEvidence']['noseWidthPixels']['exactlyUnchanged']


@pytest.mark.parametrize(('width', 'status'), [
    (92., 'within_limit'), (108., 'within_limit'),
    (91.9, 'needs_review'), (108.1, 'needs_review'),
])
def test_cosmetic_mouth_width_over_eight_percent_needs_review(monkeypatch, width, status):
    from makeup_refine import quality
    before = dict(leftEyeOpeningPixels=20., rightEyeOpeningPixels=20., noseWidthPixels=60., mouthWidthPixels=100.)
    after = dict(before, mouthWidthPixels=width)
    monkeypatch.setattr(quality, 'paired_facial_metrics', lambda *args: (before, after, {}))
    report = quality.validate_facial_proportions(None, None, None)
    assert 'mouthWidthPixels' not in report['facialProportionLimits']
    assert report['mouthWidthReview']['status'] == status
    assert report['mouthWidthReview']['relativeLimit'] == .08
    assert report['maxFacialProportionChange'] == 0


def test_eyeshadow_detector_drift_does_not_count_as_eye_closure(monkeypatch):
    from makeup_refine import quality
    p = landmarks()
    original = Image.new('RGB', (800, 1200), 'gray')
    candidate = original.copy()
    # Makeup away from the protected aperture changes the model's lid reading.
    candidate.putpixel((200, 300), (110, 110, 110))
    before = dict(leftEyeOpeningPixels=48., rightEyeOpeningPixels=48.,
                  noseWidthPixels=96., mouthWidthPixels=160.)
    after = dict(before, leftEyeOpeningPixels=48 * .948)
    monkeypatch.setattr(quality, 'paired_facial_metrics',
                        lambda *_: (before, after, {}))
    report = quality.validate_facial_proportions(
        candidate, original, None, original_landmarks=p)
    assert report['facialProportionRelativeChanges']['leftEyeOpeningPixels'] == pytest.approx(-.052)
    assert report['eyeOpeningLandmarkShiftOnly'] == ['leftEyeOpeningPixels']
    assert report['eyeAperturePixelEvidence']['leftEyeOpeningPixels']['changedPixels'] == 0

    # A real edit inside the visible eye must still be rejected.
    candidate.putpixel((280, 480), (110, 110, 110))
    with pytest.raises(quality.SpikeError, match='eye opening must not decrease'):
        quality.validate_facial_proportions(candidate, original, None,
                                            original_landmarks=p)
