import base64
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from makeup_refine import vercel_app
from makeup_refine.public_guard import SignedVisitors


def photo_bytes():
    stream = BytesIO()
    Image.new('RGB', (64, 64), '#ae8278').save(stream, 'PNG')
    return stream.getvalue()


class FakeGuard(SignedVisitors):
    def __init__(self, reason=None):
        super().__init__('test-secret')
        self.reason = reason
        self.events = []
        self.reservations = 0
        self.releases = []
        self.daily_limit = 50

    def remaining(self, visitor):
        return {'visitorRemaining': 2, 'dailyRemaining': 50, 'resetAt': '2026-10-03T00:00:00+00:00'}

    def reserve(self, visitor, job_id):
        self.reservations += 1
        return self.reason

    def release(self, visitor, job_id):
        self.releases.append(job_id)

    def event(self, name, visitor, job_id=None, detail=None):
        self.events.append((name, job_id, detail))


def request(method, path, body=b'', cookie=''):
    handler = object.__new__(vercel_app.VercelHandler)
    handler.path = path
    handler.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/json',
                       'Cookie': cookie}
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    headers = {}
    handler.send_response = lambda status: setattr(handler, 'status', status)
    handler.send_header = lambda name, value: headers.__setitem__(name, value)
    handler.end_headers = lambda: None
    getattr(handler, method)()
    return handler.status, handler.wfile.getvalue(), headers


def test_vercel_job_returns_image_only_in_response_and_deletes_working_files(tmp_path, monkeypatch):
    guard = FakeGuard()
    monkeypatch.setattr(vercel_app, '_GUARD', guard)
    monkeypatch.setattr(vercel_app, 'ROOT', tmp_path)
    model = tmp_path / 'models' / 'face_landmarker.task'
    model.parent.mkdir()
    model.write_bytes(b'model')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    working = []

    def fake_run(command, **kwargs):
        output = Path(command[command.index('--output') + 1])
        working.append(output.parent)
        output.mkdir()
        (output / 'originalImage.png').write_bytes(photo_bytes())
        (output / 'enhancedImage.png').write_bytes(photo_bytes())
        (output / 'result.json').write_text(json.dumps({
            'status': 'completed', 'enhancedImage': 'enhancedImage.png', 'steps': [],
        }))
        (output / 'api-usage.json').write_text(json.dumps({'recordedCalls': 1, 'calls': [{}]}))
        return type('Completed', (), {'returncode': 0})()

    monkeypatch.setattr(vercel_app.subprocess, 'run', fake_run)
    body = json.dumps({'style': 'Auto', 'image': base64.b64encode(photo_bytes()).decode()}).encode()
    status, payload, headers = request('do_POST', '/api/generate', body)
    job = json.loads(payload)
    assert status == 200
    assert job['originalUrl'] == 'client:original'
    assert job['afterUrl'].startswith('data:image/jpeg;base64,')
    assert job['reviewUrl'] is None and job['uploadedUrl'] is None
    assert not working[0].exists()
    assert 'Secure' in headers['Set-Cookie']
    assert guard.reservations == 1
    assert guard.releases == []
    assert ('generation_finished', job['id'], 'completed') in guard.events


def test_vercel_quota_rejects_before_photo_is_written(tmp_path, monkeypatch):
    guard = FakeGuard('DAILY_LIMIT')
    monkeypatch.setattr(vercel_app, '_GUARD', guard)
    monkeypatch.setattr(vercel_app, 'ROOT', tmp_path)
    model = tmp_path / 'models' / 'face_landmarker.task'
    model.parent.mkdir()
    model.write_bytes(b'model')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.setattr(vercel_app.subprocess, 'run', lambda *_args, **_kwargs:
                        (_ for _ in ()).throw(AssertionError('generation must not start')))
    body = json.dumps({'style': 'Auto', 'image': base64.b64encode(photo_bytes()).decode()}).encode()
    status, payload, _ = request('do_POST', '/api/generate', body)
    assert status == 429 and json.loads(payload)['code'] == 'DAILY_LIMIT'
    assert guard.reservations == 1


def test_vercel_refunds_photo_rejected_before_any_api_call(tmp_path, monkeypatch):
    guard = FakeGuard()
    monkeypatch.setattr(vercel_app, '_GUARD', guard)
    monkeypatch.setattr(vercel_app, 'ROOT', tmp_path)
    model = tmp_path / 'models' / 'face_landmarker.task'
    model.parent.mkdir()
    model.write_bytes(b'model')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')

    def fake_run(command, **kwargs):
        output = Path(command[command.index('--output') + 1])
        output.mkdir()
        (output / 'originalImage.png').write_bytes(photo_bytes())
        (output / 'result.json').write_text(json.dumps({
            'status': 'failed', 'errorCode': 'IMAGE_BLURRY', 'inputRejected': True,
            'message': 'Try a clearer photo.',
        }))
        return type('Completed', (), {'returncode': 1, 'stderr': b''})()

    monkeypatch.setattr(vercel_app.subprocess, 'run', fake_run)
    body = json.dumps({'style': 'Auto', 'image': base64.b64encode(photo_bytes()).decode()}).encode()
    status, payload, _ = request('do_POST', '/api/generate', body)
    assert status == 200
    assert json.loads(payload)['inputRejected'] is True
    assert guard.reservations == 1 and len(guard.releases) == 1


def test_vercel_keeps_quota_after_a_provider_request_even_if_result_fails(tmp_path, monkeypatch):
    guard = FakeGuard()
    monkeypatch.setattr(vercel_app, '_GUARD', guard)
    monkeypatch.setattr(vercel_app, 'ROOT', tmp_path)
    model = tmp_path / 'models' / 'face_landmarker.task'
    model.parent.mkdir()
    model.write_bytes(b'model')
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')

    def fake_run(command, **kwargs):
        output = Path(command[command.index('--output') + 1])
        output.mkdir()
        (output / 'originalImage.png').write_bytes(photo_bytes())
        (output / 'result.json').write_text(json.dumps({'status': 'failed'}))
        (output / 'api-usage.json').write_text(json.dumps({'recordedCalls': 1, 'calls': [{}]}))
        return type('Completed', (), {'returncode': 1, 'stderr': b''})()

    monkeypatch.setattr(vercel_app.subprocess, 'run', fake_run)
    body = json.dumps({'style': 'Auto', 'image': base64.b64encode(photo_bytes()).decode()}).encode()
    status, _, _ = request('do_POST', '/api/generate', body)
    assert status == 200
    assert guard.reservations == 1 and guard.releases == []


def test_redis_guard_never_sends_photo_data_and_fails_closed(monkeypatch):
    from makeup_refine.redis_guard import RedisGuard

    class Client:
        def __init__(self):
            self.calls = []

        def post(self, url, json, headers):
            self.calls.append(json)
            result = [0, 0] if json[0] == 'MGET' else 0
            return type('Response', (), {'raise_for_status': lambda self: None,
                                         'json': lambda self: {'result': result}})()

    client = Client()
    guard = RedisGuard('test-secret', 'https://example.upstash.io', 'token', client=client)
    assert guard.remaining('visitor')['dailyRemaining'] == 50
    assert guard.reserve('visitor', 'a' * 32) is None
    assert client.calls[-1][0] == 'EVAL'
    assert 'photo' not in json.dumps(client.calls)


def test_redis_refund_targets_the_day_of_the_original_reservation():
    from datetime import datetime, timezone
    from makeup_refine.redis_guard import RedisGuard

    class Client:
        def __init__(self):
            self.calls = []

        def post(self, url, json, headers):
            self.calls.append(json)
            result = '2026-10-02' if json[0] == 'GET' else 1
            return type('Response', (), {'raise_for_status': lambda self: None,
                                         'json': lambda self: {'result': result}})()

    client = Client()
    guard = RedisGuard('test-secret', 'https://example.upstash.io', 'token', client=client)
    assert guard.release('visitor', 'a' * 32,
                         datetime(2026, 10, 3, tzinfo=timezone.utc)) == 1
    refund = client.calls[-1]
    assert refund[0] == 'EVAL'
    assert 'makeup:q:2026-10-02:all' in refund
    assert 'makeup:q:2026-10-03:all' not in refund
