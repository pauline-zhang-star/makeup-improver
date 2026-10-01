"""Private reproducible API artifacts: payloads and image bytes, never auth headers."""
import base64
import hashlib
import json
from pathlib import Path


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


class TrialTrace:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.root = self.directory / 'api-trace'
        self.root.mkdir(exist_ok=True, mode=0o700)
        self.index = self.root / 'index.json'
        self.calls = json.loads(self.index.read_text()) if self.index.exists() else []

    def begin(self, record, kwargs):
        folder = self.root / record['id']
        folder.mkdir(mode=0o700)
        self.calls.append({'id': record['id'], 'stage': record['stage'], 'model': record['model'],
                           'endpoint': record['endpoint'], 'status': 'in_flight',
                           'request': str((folder / 'request.json').relative_to(self.directory))})
        payload = {k: v for k, v in kwargs.items() if k in ('json', 'data', 'files')}
        write_json(folder / 'request.json', self._externalize(payload, folder))
        write_json(self.index, self.calls)

    def _externalize(self, value, folder):
        if isinstance(value, str) and value.startswith('data:image/') and ';base64,' in value:
            return self._externalize(base64.b64decode(value.split(',', 1)[1]), folder)
        if isinstance(value, bytes):
            digest = hashlib.sha256(value).hexdigest()
            path = folder / (digest + '.png')
            path.write_bytes(value)
            return {'file': str(path.relative_to(self.directory)), 'sha256': digest, 'bytes': len(value)}
        if isinstance(value, dict):
            return {k: self._externalize(base64.b64decode(v) if k == 'b64_json' and isinstance(v, str) else v, folder)
                    for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._externalize(v, folder) for v in value]
        return value

    def finish(self, record, response=None):
        call = next(c for c in self.calls if c['id'] == record['id'])
        call['status'] = 'transport_error' if response is None else ('response_received' if response.is_success else 'http_error')
        if response is not None:
            folder = self.root / record['id']
            # Capture the actual response, even when later schema/image validation fails.
            (folder / 'response-body.json').write_bytes(response.content)
            try:
                payload = self._externalize(response.json(), folder)
            except (ValueError, TypeError):
                payload = {'unparsedResponse': 'response-body.json'}
            write_json(folder / 'response.json', payload)
            call.update(response=str((folder / 'response.json').relative_to(self.directory)),
                        httpStatus=response.status_code)
        write_json(self.index, self.calls)


def trace_for_report(directory):
    path = directory / 'api-trace' / 'index.json'
    if not path.exists():
        return []
    calls = json.loads(path.read_text())
    return [{**c, 'requestPayload': json.loads((directory / c['request']).read_text()),
             'responsePayload': json.loads((directory / c['response']).read_text()) if c.get('response') else None}
            for c in calls]
