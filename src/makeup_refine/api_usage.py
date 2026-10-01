"""Usage reported by the API, priced locally; never a billing receipt."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

PRICE_DATE = '2026-09-30'
PRICE_SOURCE = 'https://developers.openai.com/api/docs/pricing'
# USD per million tokens, standard synchronous requests; taxes excluded.
RATES = {
    'gpt-4.1-mini': {'input': .40, 'cached_input': .10, 'output': 1.60},
    'gpt-4.1-mini-2025-04-14': {'input': .40, 'cached_input': .10, 'output': 1.60},
    # Direct Images edits have no cached-input discount.
    'gpt-image-2': {'text_input': 2.50, 'image_input': 4., 'output': 15.},
}


def count(value):
    return value if type(value) is int and value >= 0 else None


def safe_usage(value):
    """Keep numeric token counters only, never content or credential strings."""
    if not isinstance(value, dict):
        return None
    clean = {}
    for key, item in value.items():
        if key.endswith('_tokens') and count(item) is not None:
            clean[key] = item
        elif key.endswith('_tokens_details') and isinstance(item, dict):
            clean[key] = safe_usage(item)
    return clean or None


def estimate(model, endpoint, usage):
    rates = RATES.get(model)
    if not rates or not usage:
        return None
    if endpoint == 'chat/completions' and 'input' in rates:
        incoming, outgoing = count(usage.get('prompt_tokens')), count(usage.get('completion_tokens'))
        cached = count((usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0))
        if incoming is None or outgoing is None or cached is None or cached > incoming:
            return None
        components = [(incoming-cached, rates['input']), (cached, rates['cached_input']),
                      (outgoing, rates['output'])]
    elif endpoint == 'images/edits' and 'image_input' in rates:
        details = usage.get('input_tokens_details') or {}
        text, image = count(details.get('text_tokens')), count(details.get('image_tokens'))
        incoming, outgoing = count(usage.get('input_tokens')), count(usage.get('output_tokens'))
        if None in (text, image, incoming, outgoing) or text + image != incoming:
            return None
        output_details = usage.get('output_tokens_details')
        if output_details and (output_details.get('text_tokens', 0) != 0 or
                               output_details.get('image_tokens', outgoing) != outgoing):
            return None  # No published text-output rate in this price snapshot.
        components = [(text, rates['text_input']), (image, rates['image_input']),
                      (outgoing, rates['output'])]
    else:
        return None
    return float(sum(Decimal(n) * Decimal(str(rate)) for n, rate in components) / Decimal(1000000))


class UsageLedger:
    def __init__(self):
        self.calls = []
        self.historical_usage_missing = False
        self.sink = None

    def snapshot(self):
        stages = {}
        for call in self.calls:
            group = stages.setdefault(call['stage'], {'calls': 0, 'knownEstimatedUSD': 0., 'unpricedCalls': 0})
            group['calls'] += 1
            cost = call['estimatedUSD']
            group['knownEstimatedUSD'] = round(group['knownEstimatedUSD'] + (cost or 0), 8)
            group['unpricedCalls'] += int(cost is None)
        subtotal = round(sum(c['estimatedUSD'] or 0 for c in self.calls), 8)
        unpriced = sum(c['estimatedUSD'] is None for c in self.calls)
        complete = not self.historical_usage_missing and unpriced == 0
        return {'currency': 'USD', 'estimateOnly': True, 'taxIncluded': False,
                'historicalUsageMissing': self.historical_usage_missing,
                'complete': complete, 'recordedCalls': len(self.calls), 'unpricedCalls': unpriced,
                'knownEstimatedUSD': subtotal, 'totalEstimatedUSD': subtotal if complete else None,
                'byStage': stages, 'calls': self.calls}

    def notify(self):
        if self.sink:
            self.sink(self.snapshot())

    def begin(self, stage, endpoint, model):
        record = {'id': str(uuid4()), 'startedAt': datetime.now(timezone.utc).isoformat(),
                  'stage': stage, 'endpoint': endpoint, 'model': model,
                  'status': 'in_flight', 'usage': None, 'estimatedUSD': None,
                  'priceDate': PRICE_DATE, 'priceSource': PRICE_SOURCE,
                  'ratesPerMillionUSD': RATES.get(model)}
        self.calls.append(record)
        self.notify()
        return record

    def finish(self, record, response=None):
        record['status'] = 'transport_error' if response is None else ('response_received' if response.is_success else 'http_error')
        if response is not None:
            record['httpStatus'] = response.status_code
            record['requestId'] = response.headers.get('x-request-id')
            try:
                body = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict):
                record['usage'] = safe_usage(body.get('usage'))
            record['estimatedUSD'] = estimate(record['model'], record['endpoint'], record['usage'])
        self.notify()


def attach_usage(provider, directory, report, historical=False):
    """Persist each transition, including failed calls, independently of result status."""
    import json
    ledger = getattr(provider, 'usage_ledger', None)
    if ledger is None:  # Protocol implementations without remote calls need no accounting.
        return
    path = directory / 'api-usage.json'
    previous = json.loads(path.read_text()) if path.exists() else report.get('apiUsage')
    if previous:
        ledger.calls = previous['calls']
        ledger.historical_usage_missing = previous.get('historicalUsageMissing', False)
    else:
        ledger.historical_usage_missing = historical

    def write_json(path, data):
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        temporary.replace(path)

    def save(snapshot):
        report['apiUsage'] = snapshot
        write_json(path, snapshot)
        result_path = directory / 'result.json'
        if result_path.exists():
            # Preserve the last usable image/report if a retry or process fails.
            saved = json.loads(result_path.read_text())
            saved['apiUsage'] = snapshot
            write_json(result_path, saved)
    ledger.sink = save
    ledger.notify()
