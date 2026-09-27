"""Render observed steps, never the legacy fixed technique instructions."""
from html import escape


def look_steps_html(report):
    status = report['status']
    if status == 'failed':
        body = '<p>' + escape(report.get('message', 'The image could not be generated.')) + '</p>'
    elif status == 'instructions_unavailable':
        body = '<p>The image is saved. Makeup steps are unavailable; retry the comparison without generating another image.</p>'
    elif status == 'candidate_rejected':
        body = '<p>The candidate moved facial landmarks beyond the allowed limit. No makeup steps were generated.</p>'
    elif status == 'rejected':
        body = '<p>This result changed more than makeup and has not been accepted. No makeup steps are shown.</p>'
    elif status == 'enhanced_ready':
        body = '<p>Your image is ready. Comparing the original and enhanced photos to prepare the steps.</p>'
    elif not report.get('steps'):
        body = '<p>No confident visible makeup changes were identified. No extra steps have been invented.</p>'
    else:
        cards = []
        for number, step in enumerate(report['steps'], 1):
            cards.append(f'<li id="look-step-{number}"><span class="step-number">{number}</span><div><strong>' + escape(step['area'].replace('_', ' ').title()) + '</strong><p>'
                         + escape(step['instruction']) + '</p><details><summary>What changed</summary><p>Before: '
                         + escape(step['before']) + '</p><p>After: ' + escape(step['after']) + '</p></details></div></li>')
        body = '<ol class="look-steps">' + ''.join(cards) + '</ol>'
    return '<section><h2>How to Achieve This Look</h2>' + body + '</section>'
