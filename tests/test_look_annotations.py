import re
import math
from PIL import Image
from makeup_refine.look_annotations import annotation_anchors, after_annotations_html, short_arrow
from makeup_refine.look_view import look_steps_html
from makeup_refine.report import write_report
from flow_fixtures import Detector


def report(areas):
    return {'status': 'completed', 'annotationAnchors': annotation_anchors(Detector().detect(None)[0]),
            'steps': [dict(area=area, instruction='Apply and blend.', before='Before', after='After') for area in areas]}


def test_numbers_match_step_order_even_when_areas_are_missing_or_reordered():
    result = report(['lips', 'eyebrows', 'complexion'])
    annotations = after_annotations_html(result, (768, 1024))
    instructions = look_steps_html(result)
    assert re.findall(r'data-callout="(\d+)"', annotations) == ['1', '2', '3']
    assert re.findall(r'id="look-step-(\d+)"', instructions) == ['1', '2', '3']
    assert instructions.index('Lips') < instructions.index('Eyebrows') < instructions.index('Complexion')


def test_nose_contour_step_has_matching_callout_and_readable_name():
    result = report(['nose_contour'])
    assert 'data-callout="1"' in after_annotations_html(result, (768, 1024))
    assert 'Nose Contour' in look_steps_html(result)


def test_all_area_anchors_are_normalized_and_labels_are_separated():
    anchors = annotation_anchors(Detector().detect(None)[0])
    assert len(anchors) == 8
    assert 'nose_contour' in anchors
    for value in anchors.values():
        assert all(0 <= v <= 1 for v in value['label'] + value['target'])
    for side in {v['label'][0] for v in anchors.values()}:
        ys = sorted(v['label'][1] for v in anchors.values() if v['label'][0] == side)
        assert all(b - a >= .064 for a, b in zip(ys, ys[1:]))


def test_rejected_or_missing_anchors_have_no_arrows():
    result = report(['lips'])
    result['status'] = 'rejected'
    assert after_annotations_html(result, (768, 1024)) == ''
    result['status'] = 'completed'
    result['annotationAnchors']['lips']['target'] = [float('nan'), .5]
    assert after_annotations_html(result, (768, 1024)) == ''


def test_annotations_and_after_image_share_the_same_clipped_layer(tmp_path):
    path = tmp_path / 'review.html'
    image = Image.new('RGB', (768, 1024), 'gray')
    write_report(path, image, masks={}, result=image, look_result=report(['lips']))
    html = path.read_text()
    after_start = html.index('<div id="refined" data-refined>')
    annotations = html.index('<div class="after-annotations"')
    divider = html.index('<span id="divider" data-divider>')
    assert after_start < annotations < divider
    assert 'clip-path:inset(0 50% 0 0)' in html
    assert "panel.querySelector('[data-refined]').style.clipPath" in html
    assert 'pointer-events:none' in html


def test_arrows_approach_but_keep_a_gap_before_features():
    for label, target in [((.25, .35), (.43, .35)), ((.82, .43), (.70, .40)),
                          ((.82, .59), (.65, .57)), ((.82, .30), (.56, .30))]:
        tip = short_arrow(label, target, (768, 1024))
        assert tip is not None
        length = math.hypot(tip[0] - label[0]*768, tip[1] - label[1]*1024)
        gap = math.hypot(tip[0] - target[0]*768, tip[1] - target[1]*1024)
        assert length <= .25*768 + 1e-6
        assert gap >= .028*768 - 1e-6
    assert short_arrow((.5, .5), (.51, .5), (768, 1024)) is None


def test_stroke_stops_before_any_protected_feature_not_only_target():
    tip = short_arrow((.2, .4), (.6, .4), (768, 1024), [[.35, .3, .45, .5]])
    assert tip[0] < .35 * 768
    assert short_arrow((.4, .4), (.6, .4), (768, 1024), [[.35, .3, .45, .5]]) is None


def test_rejected_trial_shows_plan_arrows_with_matching_labels_not_observed_steps():
    r = report([])
    r.update(status='failed', candidateImage='candidate.png', techniquePlan={'selected': [
        {'technique_id': 'brow_08', 'region': 'brows', 'application': 'Draw soft hair strokes.'},
        {'technique_id': 'lips_03', 'region': 'lips', 'application': 'Adjust lip hue.'}]})
    arrows = after_annotations_html(r, (768, 1024))
    text = look_steps_html(r)
    assert re.findall(r'data-callout="(\d+)"', arrows) == ['1', '2']
    assert re.findall(r'id="look-step-(\d+)"', text) == ['1', '2']
    assert '尚未确认生成效果' in text
    assert not r['steps']
