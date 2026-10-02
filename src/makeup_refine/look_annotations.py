"""Presentation-only callouts. Source PNGs remain unmarked and independent."""
import math
from .landmarks import LIPS, UPPER_EYES, LOWER_EYES


def short_arrow(label, target, size, protected=()):
    """Approach the feature without entering padded feature rectangles."""
    w, h = size
    dx, dy = (target[0] - label[0]) * w, (target[1] - label[1]) * h
    distance = math.hypot(dx, dy)
    length = min(.25 * w, distance - .028 * w)
    # Intersect the whole stroke with every protected feature, not just its target.
    for x0, y0, x1, y1 in protected:
        enter, leave = 0., 1.
        for start, delta, low, high in ((label[0], target[0]-label[0], x0, x1),
                                       (label[1], target[1]-label[1], y0, y1)):
            if abs(delta) < 1e-9:
                if not low <= start <= high:
                    enter, leave = 1., 0.
                    break
            else:
                a, b = sorted(((low-start)/delta, (high-start)/delta))
                enter, leave = max(enter, a), min(leave, b)
        if enter <= leave:
            length = min(length, enter * distance - .004 * w)
    if length < .025 * w or distance == 0:
        return None
    fraction = length / distance
    return label[0] * w + dx * fraction, label[1] * h + dy * fraction


def annotation_anchors(points):
    def point(index):
        return [float(v) for v in points[index]]
    def midpoint(a, b):
        return [(points[a][i] + points[b][i]) / 2 for i in (0, 1)]
    left = max(.045, min(p[0] for p in points) - .065)
    right = min(.955, max(p[0] for p in points) + .065)
    feature_groups = [
        [70, 63, 105, 66, 107, 55, 65, 52, 53, 46],
        [300, 293, 334, 296, 336, 285, 295, 282, 283, 276],
        UPPER_EYES[0] + LOWER_EYES[0], UPPER_EYES[1] + LOWER_EYES[1],
        [1, 2, 98, 327, 168, 6, 197], LIPS,
    ]
    protected = [[min(points[i][0] for i in group)-.02,
                  min(points[i][1] for i in group)-.015,
                  max(points[i][0] for i in group)+.02,
                  max(points[i][1] for i in group)+.015] for group in feature_groups]
    targets = {
        'eyebrows': (point(105), left),
        'eyeliner': (point(263), right),
        'lashes': (point(159), left),
        'eyeshadow': (midpoint(386, 334), right),
        'nose_contour': (point(197), left),
        'blush': (point(205), left),
        'lips': (point(291), right),
        'complexion': (midpoint(10, 151), right),
    }
    anchors = {}
    for side in (left, right):
        previous = .025
        for area, (target, x) in sorted(targets.items(), key=lambda item: item[1][0][1]):
            if x != side:
                continue
            y = min(.955, max(target[1], previous + .065))
            previous = y
            anchors[area] = {'target': target, 'label': [x, y], 'protected': protected}
    return anchors


def planned_review_steps(report):
    """Review-only plan labels, never claimed observed changes."""
    if report.get('status') not in ('failed', 'rejected', 'candidate_rejected', 'instructions_unavailable'):
        return []
    if not (report.get('candidateImage') or report.get('alignedCandidateImage') or report.get('enhancedImage')):
        return []
    mapping = {'brows': 'eyebrows', 'foundation': 'complexion'}
    grouped = {}
    for item in (report.get('techniquePlan') or {}).get('selected', []):
        area = mapping.get(item['region'], item['region'])
        instruction = item.get('application') or item.get('instruction', '')
        if area not in grouped:
            grouped[area] = {'area': area, 'instruction': instruction,
                             'instruction_zh': item.get('application_zh'),
                             'technique_id': item['technique_id']}
        else:
            grouped[area]['instruction'] += ' ' + instruction
            if grouped[area]['instruction_zh'] and item.get('application_zh'):
                grouped[area]['instruction_zh'] += ' ' + item['application_zh']
            else:
                grouped[area]['instruction_zh'] = None
            grouped[area]['technique_id'] += ' + ' + item['technique_id']
    return list(grouped.values())



def after_annotations_html(report, size):
    steps = report.get('steps', []) if report.get('status') == 'completed' else planned_review_steps(report)
    if not steps:
        return ''
    anchors = report.get('annotationAnchors', {})
    w, h = size
    lines, badges = [], []
    for number, step in enumerate(steps, 1):
        anchor = anchors.get(step['area'])
        if not anchor:
            continue
        try:
            x, y = (float(v) for v in anchor['label'])
            tx, ty = (float(v) for v in anchor['target'])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in (x, y, tx, ty)):
            continue
        tip = short_arrow((x, y), (tx, ty), size, anchor.get('protected', ()))
        if tip is not None:
            segment = f'x1="{x*w}" y1="{y*h}" x2="{tip[0]}" y2="{tip[1]}"'
            lines.append(f'<line class="callout-halo" {segment}/><line class="callout-line" {segment} marker-end="url(#callout-tip)"/>')
        badges.append(f'<span class="callout-number" data-callout="{number}" style="left:{x*100}%;top:{y*100}%">{number}</span>')
    if not badges:
        return ''
    return (f'<div class="after-annotations" aria-hidden="true"><svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            '<defs><marker id="callout-tip" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#842e59" stroke="white" stroke-width=".7"/></marker></defs>'
            + ''.join(lines) + '</svg>' + ''.join(badges) + '</div>')
