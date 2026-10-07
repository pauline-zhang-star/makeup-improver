"""Signed continuation metadata; photos stay with the client between requests."""
import base64
import hashlib
import hmac
import json
import time

TTL = 3600


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
