"""Signed continuation metadata; photos stay with the client between requests."""
import base64
import hashlib
import hmac
import json
import time
from copy import deepcopy

TTL = 3600


def evidence_for_display(evidence, size):
    """Keep detail crops aligned if the matched display pair was downscaled."""
    if not evidence or tuple(evidence.get('imageSize', size)) == tuple(size):
        return evidence
    result = deepcopy(evidence)
    old_width, old_height = result['imageSize']
    width, height = size
    for region in result.get('regions', []):
        region['cropBoxes'] = [[round(x0 * width / old_width), round(y0 * height / old_height),
                                round(x1 * width / old_width), round(y1 * height / old_height)]
                               for x0, y0, x1, y1 in region.get('cropBoxes', [])]
    result['pixelMetricsSourceSize'] = result['imageSize']
    result['imageSize'] = list(size)
    result['alignment'] = 'Matched display pair; crops scaled together. Pixel metrics were measured on the original working pair before JPEG encoding.'
    return result


def issue(secret, visitor, job_id, report, before, after, now=None):
    # No file paths, raw prompts, credentials or photo bytes in the ticket.
    fields = ('flow', 'requestedStyle', 'editModel', 'visionModel', 'generationMode',
              'techniquePlan', 'comparisonEvidence', 'annotationAnchors',
              'allowedSupplementaryAreas', 'mouthWidthReview', 'apiUsage', 'guidanceDeferred')
    payload = {'id': job_id, 'owner': visitor, 'exp': int(now or time.time()) + TTL,
               'before': hashlib.sha256(before.encode()).hexdigest(),
               'after': hashlib.sha256(after.encode()).hexdigest(),
               'report': {key: report[key] for key in fields if key in report}}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode()
    signature = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + signature


def verify(secret, visitor, ticket, before, after, now=None):
    if not isinstance(ticket, str) or len(ticket) > 600_000:
        raise ValueError('Invalid instructions request.')
    try:
        body, signature = ticket.rsplit('.', 1)
        expected = hmac.new(secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError('Invalid instructions request.')
        payload = json.loads(base64.urlsafe_b64decode(body))
        if payload['owner'] != visitor or payload['exp'] <= (now or time.time()):
            raise ValueError('This preview expired. Generate a new look.')
        for key, image in [('before', before), ('after', after)]:
            if not isinstance(image, str) or hashlib.sha256(image.encode()).hexdigest() != payload[key]:
                raise ValueError('The preview images changed. Generate a new look.')
        return payload
    except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid instructions request.') from exc
