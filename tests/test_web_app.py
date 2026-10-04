import base64
import json
from io import BytesIO

from PIL import Image

from makeup_refine import web_app


def png_bytes():
    stream = BytesIO()
    Image.new('RGB', (48, 48), '#bc8c84').save(stream, 'PNG')
    return stream.getvalue()


def test_public_job_keeps_failed_candidate_diagnostic_and_planned_guidance(tmp_path):
    job_id = 'a' * 32
    directory = tmp_path / job_id
    directory.mkdir()
    (directory / 'originalImage.png').write_bytes(png_bytes())
    (directory / 'candidateImage.png').write_bytes(png_bytes())
    (directory / 'uploadedImage.png').write_bytes(png_bytes())
    report = {
        'status': 'rejected', 'requestedStyle': 'Date Night', 'candidateImage': 'candidateImage.png',
        'techniqueAnalysis': {'region_decisions': [
            {'kind': 'propose', 'technique_id': 'lips_01',
             'structured_evidence': {'region': 'lips'}},
            {'kind': 'preserve', 'region': 'brows', 'reason': 'Already defined.'}]},
        'inputCrop': {'sourceSize': [48, 96], 'workingSize': [48, 48],
                      'cropBox': [0, 24, 48, 72], 'reasons': ['paired_black_letterbox']},
        'techniquePlan': {'look_direction': 'Richer lips with preserved brows.',
                          'preserved_areas': [{'region': 'brows', 'reason': 'Already defined.'}],
                          'selected': [{'technique_id': 'lips_01', 'region': 'lips',
                                       'instruction': 'Define the lip outline.',
                                       'application_zh': '沿原有唇线轻轻勾勒。',
                                       'selection_basis': 'style_baseline',
                                       'evidence': [{'feature': 'lip_edge_visible', 'measured_value': True}]}]},
        'annotationAnchors': {'lips': {'label': [.9, .7], 'target': [.6, .7], 'protected': []}},
        'generationAttempts': [{'status': 'rejected', 'checks': {'geometry': {'status': 'failed'}}}],
        'apiUsage': {'totalEstimatedUSD': .0123, 'complete': True},
    }
    (directory / 'result.json').write_text(json.dumps(report))
    job = web_app.public_job(job_id, directory)
    assert job['diagnostic'] is True
    assert job['afterUrl'] == f'/api/jobs/{job_id}/after'
    assert job['plannedGuides'][0]['instruction'] == 'Define the lip outline.'
    assert job['plannedGuides'][0]['instruction_zh'] == '沿原有唇线轻轻勾勒。'
    assert job['planned'][0]['instruction_zh'] == '沿原有唇线轻轻勾勒。'
    assert job['callouts'][0]['number'] == 1
    assert job['planned'][0]['basis'] == 'style_baseline'
    assert job['planAvailable'] is True
    assert job['lookDirection'] == 'Richer lips with preserved brows.'
    assert [item['kind'] for item in job['planningDecisions']] == ['propose', 'preserve']
    assert job['preserved'] == [{'region': 'brows', 'reason': 'Already defined.'}]
    assert job['attempts'][0]['checks']['geometry'] == 'failed'
    assert job['cost'] == .0123
    assert job['inputCrop']['workingSize'] == [48, 48]
    assert job['uploadedUrl'] == f'/api/jobs/{job_id}/uploaded'


def test_public_job_identifies_reframe_in_saved_trial(tmp_path):
    directory = tmp_path / ('b' * 32)
    directory.mkdir()
    report = {'status': 'failed', 'planningFailure': {'phase': 'model_schema',
              'issues': [{'field': 'region_decisions', 'type': 'missing'}]},
              'generationAttempts': [{
        'status': 'rejected', 'scale': 1.18756, 'landmarkResidualAfterFit': .00486,
        'checks': {'registration': {'status': 'failed'}}}]}
    (directory / 'result.json').write_text(json.dumps(report))
    job = web_app.public_job('b' * 32, directory)
    assert job['providerReframing'] == {'faceScaleChangePercent': 18.8}
    assert job['planAvailable'] is False
    assert job['planningFailure']['issues'][0]['field'] == 'region_decisions'


def test_web_handlers_upload_and_static_routes_without_api_call(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, 'UPLOADS', tmp_path / 'uploads')
    monkeypatch.setattr(web_app, 'RUNS', tmp_path / 'runs')
    monkeypatch.setattr(web_app, 'STATE_DB', tmp_path / 'access.sqlite3')
    monkeypatch.setattr(web_app, '_ACCESS_STORE', None)
    monkeypatch.setattr(web_app, 'JOB_PROCESSES', {})

    class FakeProcess:
        def poll(self):
            return None

    calls = []
    monkeypatch.setattr(web_app.subprocess, 'Popen', lambda *args, **kwargs:
                        (calls.append((args, kwargs)) or FakeProcess()))

    def request(method, path, body=b''):
        handler = object.__new__(web_app.WebHandler)
        handler.path = path
        handler.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/json'}
        handler.rfile = BytesIO(body)
        handler.wfile = BytesIO()
        handler.send_response = lambda status: setattr(handler, 'status', status)
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None
        getattr(handler, method)()
        return handler.status, handler.wfile.getvalue()

    assert b'photo-input' in request('do_GET', '/')[1]
    assert b'data-language="zh"' in request('do_GET', '/')[1]
    assert json.loads(request('do_GET', '/api/quota')[1])['limited'] is False
    assert b'splitAt' in request('do_GET', '/app.js')[1]
    assert request('do_POST', '/api/jobs', b'{"style":"invalid","image":"a"}')[0] == 400
    body = json.dumps({'style': 'Auto', 'image': base64.b64encode(png_bytes()).decode()}).encode()
    status, payload = request('do_POST', '/api/jobs', body)
    assert status == 202
    job_id = json.loads(payload)['id']
    assert len(calls) == 1
    assert (web_app.UPLOADS / f'{job_id}.png').is_file()
    heic = BytesIO()
    Image.new('RGB', (48, 48), '#bc8c84').save(heic, format='HEIF')
    heic_body = json.dumps({'style': 'Auto', 'image': base64.b64encode(heic.getvalue()).decode()}).encode()
    heic_status, heic_payload = request('do_POST', '/api/jobs', heic_body)
    assert heic_status == 202
    assert (web_app.UPLOADS / f"{json.loads(heic_payload)['id']}.heic").is_file()
    assert json.loads(request('do_GET', f'/api/jobs/{job_id}')[1])['status'] == 'starting'
    assert request('do_GET', f'/api/jobs/{job_id}/../../.env')[0] == 404


def test_existing_inverse_scale_review_is_served_as_diagnostic(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, 'RUNS', tmp_path)
    monkeypatch.setattr(web_app, 'STATE_DB', tmp_path / 'access.sqlite3')
    monkeypatch.setattr(web_app, '_ACCESS_STORE', None)
    job_id = 'c' * 32
    directory = tmp_path / job_id
    directory.mkdir()
    (directory / 'result.json').write_text('{"status":"failed"}')
    (directory / 'inverse-scale-review.html').write_text('<h1>Offline diagnostic</h1>')
    handler = object.__new__(web_app.WebHandler)
    handler.path = f'/api/jobs/{job_id}/inverse-scale-review'
    handler.headers = {}
    handler.wfile = BytesIO()
    handler.send_response = lambda status: setattr(handler, 'status', status)
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None
    handler.do_GET()
    assert handler.status == 200
    assert b'Offline diagnostic' in handler.wfile.getvalue()


def test_public_upload_limit_uses_signed_cookie_before_starting_work(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, 'PUBLIC_MODE', True)
    monkeypatch.setattr(web_app, 'VISITOR_SECRET', 'test-secret')
    monkeypatch.setattr(web_app, 'STATE_DB', tmp_path / 'state.sqlite3')
    monkeypatch.setattr(web_app, '_ACCESS_STORE', None)
    monkeypatch.setattr(web_app, 'UPLOADS', tmp_path / 'uploads')
    monkeypatch.setattr(web_app, 'RUNS', tmp_path / 'runs')
    monkeypatch.setattr(web_app, 'JOB_PROCESSES', {})

    class FakeProcess:
        def poll(self):
            return 0

    starts = []
    monkeypatch.setattr(web_app.subprocess, 'Popen', lambda *args, **kwargs:
                        (starts.append(args) or FakeProcess()))

    def request(method, path, body=b'', cookie=''):
        handler = object.__new__(web_app.WebHandler)
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
        return handler.status, json.loads(handler.wfile.getvalue()) if method == 'do_POST' else None, headers

    _, _, headers = request('do_GET', '/')
    cookie = headers['Set-Cookie'].split(';', 1)[0]
    assert 'Secure' in headers['Set-Cookie']
    body = json.dumps({'style': 'Auto', 'image': base64.b64encode(png_bytes()).decode()}).encode()
    assert request('do_POST', '/api/jobs', body, cookie)[0] == 202
    assert request('do_POST', '/api/jobs', body, cookie)[0] == 202
    status, rejected, _ = request('do_POST', '/api/jobs', body, cookie)
    assert status == 429 and rejected['code'] == 'VISITOR_LIMIT'
    assert len(starts) == 2
    assert len(list((tmp_path / 'uploads').glob('*.png'))) == 2


def test_busy_public_worker_does_not_charge_or_save_another_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, 'PUBLIC_MODE', True)
    monkeypatch.setattr(web_app, 'VISITOR_SECRET', 'test-secret')
    monkeypatch.setattr(web_app, 'STATE_DB', tmp_path / 'state.sqlite3')
    monkeypatch.setattr(web_app, '_ACCESS_STORE', None)
    monkeypatch.setattr(web_app, 'UPLOADS', tmp_path / 'uploads')
    monkeypatch.setattr(web_app, 'RUNS', tmp_path / 'runs')

    class RunningProcess:
        def poll(self):
            return None

    monkeypatch.setattr(web_app, 'JOB_PROCESSES', {'a' * 32: RunningProcess()})
    monkeypatch.setattr(web_app.subprocess, 'Popen', lambda *args, **kwargs:
                        (_ for _ in ()).throw(AssertionError('worker should stay idle')))
    body = json.dumps({'style': 'Auto', 'image': base64.b64encode(png_bytes()).decode()}).encode()
    handler = object.__new__(web_app.WebHandler)
    handler.path = '/api/jobs'
    handler.headers = {'Content-Length': str(len(body)), 'Content-Type': 'application/json'}
    handler.rfile = BytesIO(body)
    handler.wfile = BytesIO()
    handler.send_response = lambda status: setattr(handler, 'status', status)
    handler.send_header = lambda *_: None
    handler.end_headers = lambda: None
    handler.do_POST()
    assert handler.status == 503
    assert json.loads(handler.wfile.getvalue())['code'] == 'SERVER_BUSY'
    assert web_app.access_store().remaining('new-visitor')['dailyRemaining'] == 50
    assert not (tmp_path / 'uploads').exists()


def test_finished_local_preflight_refunds_without_provider_call(tmp_path, monkeypatch):
    monkeypatch.setattr(web_app, 'PUBLIC_MODE', True)
    monkeypatch.setattr(web_app, 'VISITOR_SECRET', 'test-secret')
    monkeypatch.setattr(web_app, 'STATE_DB', tmp_path / 'state.sqlite3')
    monkeypatch.setattr(web_app, '_ACCESS_STORE', None)
    monkeypatch.setattr(web_app, 'RUNS', tmp_path / 'runs')
    job_id = 'f' * 32
    visitor = 'visitor'
    store = web_app.access_store()
    assert store.reserve(visitor, job_id) is None

    class FinishedProcess:
        def poll(self):
            return 1

    monkeypatch.setattr(web_app, 'JOB_PROCESSES', {job_id: FinishedProcess()})
    monkeypatch.setattr(web_app, 'JOB_RESERVATIONS', {job_id: visitor})
    assert store.remaining(visitor)['visitorRemaining'] == 1
    web_app.settle_finished_jobs()
    web_app.settle_finished_jobs()
    assert store.remaining(visitor)['visitorRemaining'] == 2
    assert store.remaining(visitor)['dailyRemaining'] == 50
    assert web_app.JOB_RESERVATIONS == {}
