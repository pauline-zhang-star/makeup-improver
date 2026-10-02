"""Small web UI over the existing CLI pipeline, with optional public quotas."""
import argparse
import base64
import binascii
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from PIL import Image, UnidentifiedImageError

from .look_annotations import planned_review_steps, short_arrow
from .look_models import MakeupStyle
from .public_guard import AccessStore

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'web'
PUBLIC_MODE = os.environ.get('MAKEUP_PUBLIC_MODE') == '1'
TEMP_ROOT = Path(os.environ.get('MAKEUP_TEMP_DIR', ROOT / 'outputs'))
UPLOADS = TEMP_ROOT / 'web-uploads'
RUNS = TEMP_ROOT / 'web-runs'
STATE_DB = Path(os.environ.get('MAKEUP_STATE_DB', ROOT / 'outputs' / 'web-state.sqlite3'))
VISITOR_SECRET = os.environ.get('MAKEUP_VISITOR_SECRET') or secrets.token_urlsafe(32)
VISITOR_DAILY_LIMIT = int(os.environ.get('MAKEUP_VISITOR_DAILY_LIMIT', '2'))
GLOBAL_DAILY_LIMIT = int(os.environ.get('MAKEUP_GLOBAL_DAILY_LIMIT', '20'))
RESULT_TTL_SECONDS = 2 * 60 * 60
JOB_ID = re.compile(r'^[0-9a-f]{32}$')
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_REQUEST_BYTES = 17 * 1024 * 1024
MIME = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8',
        '.js': 'text/javascript; charset=utf-8', '.png': 'image/png',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}
ASSET_ROUTES = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
JOB_PROCESSES = {}
_ACCESS_STORE = None
_STORE_LOCK = threading.Lock()
_JOB_START_LOCK = threading.Lock()


def access_store():
    global _ACCESS_STORE
    with _STORE_LOCK:
        if (_ACCESS_STORE is None or _ACCESS_STORE.path != STATE_DB or
                _ACCESS_STORE.visitor_limit != VISITOR_DAILY_LIMIT or
                _ACCESS_STORE.daily_limit != GLOBAL_DAILY_LIMIT):
            _ACCESS_STORE = AccessStore(STATE_DB, VISITOR_SECRET,
                                        VISITOR_DAILY_LIMIT, GLOBAL_DAILY_LIMIT)
    return _ACCESS_STORE


def cleanup_expired():
    """Remove only this web app's expired, non-running temporary job files."""
    cutoff = time.time() - RESULT_TTL_SECONDS
    for directory in (UPLOADS, RUNS):
        if not directory.is_dir():
            continue
        for item in directory.iterdir():
            job_id = item.name.split('.', 1)[0]
            if not JOB_ID.fullmatch(job_id):
                continue
            process = JOB_PROCESSES.get(job_id)
            if process is not None and process.poll() is None:
                continue
            try:
                if item.stat().st_mtime >= cutoff:
                    continue
                if item.is_dir() and directory == RUNS:
                    shutil.rmtree(item)
                elif item.is_file() and directory == UPLOADS:
                    item.unlink()
                JOB_PROCESSES.pop(job_id, None)
            except OSError:
                continue


def cleanup_loop():
    while True:
        try:
            cleanup_expired()
            access_store().prune()
        except (OSError, sqlite3.Error) as exc:
            print(f'Temporary cleanup or metadata pruning failed: {type(exc).__name__}', file=sys.stderr)
        time.sleep(600)


def safe_job_directory(job_id):
    if not JOB_ID.fullmatch(job_id):
        return None
    directory = RUNS / job_id
    return directory if directory.is_dir() else None


def callouts_for(report, size):
    anchors = report.get('annotationAnchors') or {}
    if report.get('status') == 'completed':
        items = report.get('steps') or []
        source = 'observed'
    else:
        items = planned_review_steps(report)
        source = 'planned'
    area_map = {'brows': 'eyebrows', 'foundation': 'complexion'}
    callouts = []
    for number, item in enumerate(items, 1):
        area = area_map.get(item.get('area') or item.get('region'), item.get('area'))
        anchor = anchors.get(area)
        if not anchor:
            continue
        label = anchor['label']
        end = short_arrow(label, anchor['target'], size, anchor.get('protected', ()))
        if not end:
            continue
        callouts.append({'number': number, 'area': area, 'label': label,
                         'end': [end[0] / size[0], end[1] / size[1]], 'source': source})
    return callouts


def public_job(job_id, directory):
    result_file = directory / 'result.json'
    if not result_file.is_file():
        return {'id': job_id, 'status': 'starting'}
    report = json.loads(result_file.read_text(encoding='utf-8'))
    image_file = None
    for name in ((report.get('enhancedImage') if report.get('enhancedImage') == 'enhancedImage.png' else None),
                 report.get('alignedCandidateImage'),
                 report.get('candidateImage')):
        if name and Path(name).name == name and (directory / name).is_file():
            image_file = name
            break
    visual = bool(image_file)
    size = None
    if visual:
        with Image.open(directory / image_file) as image:
            size = image.size
    plan = report.get('techniquePlan') or {}
    selected = plan.get('selected') or []
    status = report.get('status', 'starting')
    attempts = report.get('generationAttempts') or []
    reframing = next((item for item in attempts
                      if item.get('failureType') == 'provider_reframing' or
                      (item.get('checks') or {}).get('registration', {}).get('failureType') == 'provider_reframing'), None)
    # Older saved trials predate the explicit failure type, but contain the
    # fitted face scale and residual needed to identify this same failure.
    if reframing is None:
        reframing = next((item for item in attempts
                          if (item.get('checks') or {}).get('registration', {}).get('status') == 'failed'
                          and isinstance(item.get('scale'), (int, float))
                          and abs(item['scale'] - 1) > .05
                          and isinstance(item.get('landmarkResidualAfterFit'), (int, float))
                          and item['landmarkResidualAfterFit'] <= .015), None)
    face_scale = reframing.get('scale') if reframing else None
    return {
        'id': job_id, 'status': status, 'style': report.get('requestedStyle', 'Auto'),
        'message': report.get('message'), 'errorCode': report.get('errorCode'),
        'inputQuality': report.get('inputQuality'), 'inputRejected': report.get('inputRejected', False),
        'inputCrop': report.get('inputCrop'),
        'providerReframing': ({'faceScaleChangePercent': round((face_scale - 1) * 100, 1)}
                              if isinstance(face_scale, (int, float)) else None),
        'uploadedUrl': f'/api/jobs/{job_id}/uploaded' if (directory / 'uploadedImage.png').is_file() else None,
        'retryAction': report.get('retryAction'),
        'originalUrl': f'/api/jobs/{job_id}/original' if (directory / 'originalImage.png').exists() else None,
        'afterUrl': f'/api/jobs/{job_id}/after' if visual else None,
        'diagnostic': bool(visual and report.get('enhancedImage') != 'enhancedImage.png'),
        'width': size[0] if size else None, 'height': size[1] if size else None,
        'callouts': callouts_for(report, size) if size else [],
        'steps': report.get('steps') or [],
        'planned': [{'id': x['technique_id'], 'area': x['region'],
                     'instruction': x.get('application') or x.get('instruction'),
                     'instruction_zh': x.get('application_zh'),
                     'observation': x.get('observation'), 'reason': x.get('style_reason'),
                     'basis': x.get('selection_basis'),
                     'evidence': x.get('structured_evidence') or x.get('evidence') or []}
                    for x in selected],
        'plannedGuides': planned_review_steps(report),
        'rejected': plan.get('rejected_proposals') or [],
        'pending': report.get('pendingChangeReviews') or [],
        'preservationIssues': report.get('preservationIssues') or [],
        'mouthWidthReview': report.get('mouthWidthReview'),
        'attempts': [{'status': x.get('status'), 'message': x.get('message'),
                      'checks': {key: value.get('status') for key, value in (x.get('checks') or {}).items()}}
                     for x in report.get('generationAttempts') or []],
        'cost': (report.get('apiUsage') or {}).get('totalEstimatedUSD'),
        'knownCost': (report.get('apiUsage') or {}).get('knownEstimatedUSD'),
        'costComplete': (report.get('apiUsage') or {}).get('complete'),
        'reviewUrl': f'/api/jobs/{job_id}/review' if (directory / 'review.html').is_file() else None,
    }


class WebHandler(BaseHTTPRequestHandler):
    server_version = 'MakeupRefineLocal/1.0'

    def respond(self, status, data, content_type='application/json; charset=utf-8',
                review=False, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        if cookie:
            self.send_header('Set-Cookie', AccessStore.cookie_header(cookie, PUBLIC_MODE))
        self.send_header('Content-Security-Policy',
                         "default-src 'self' data:; img-src 'self' blob: data:; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                         "connect-src 'self'; frame-ancestors 'none'" if review else
                         "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; "
                         "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def visitor(self):
        return access_store().visitor(self.headers.get('Cookie', ''))

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/health':
            self.respond(200, {'ok': True})
            return
        if path == '/api/quota':
            visitor, cookie = self.visitor()
            quota = access_store().remaining(visitor) if PUBLIC_MODE else {
                'visitorRemaining': None, 'dailyRemaining': None, 'resetAt': None}
            self.respond(200, {'limited': PUBLIC_MODE, **quota}, cookie=cookie)
            return
        if path in ASSET_ROUTES:
            name = ASSET_ROUTES[path]
            cookie = None
            if path == '/':
                visitor, cookie = self.visitor()
                query = parse_qs(self.path.split('?', 1)[1]) if '?' in self.path else {}
                job = (query.get('job') or [None])[0]
                access_store().event('page_view', visitor,
                                     job_id=job if job and JOB_ID.fullmatch(job) else None)
            self.respond(200, (ASSETS / name).read_bytes(), MIME[Path(name).suffix], cookie=cookie)
            return
        parts = path.strip('/').split('/')
        if len(parts) < 3 or parts[:2] != ['api', 'jobs']:
            self.respond(404, {'error': 'Not found.'})
            return
        job_id, directory = parts[2], safe_job_directory(parts[2])
        if directory is None and len(parts) == 3 and JOB_ID.fullmatch(job_id) and any(
                (UPLOADS / (job_id + suffix)).is_file() for suffix in ('.jpg', '.png')):
            process = JOB_PROCESSES.get(job_id)
            if process is not None and process.poll() is not None:
                self.respond(200, {'id': job_id, 'status': 'failed',
                                   'message': 'The local workflow stopped before a result was saved. Check the local log.'})
            else:
                self.respond(200, {'id': job_id, 'status': 'starting'})
            return
        if directory is None:
            if PUBLIC_MODE and JOB_ID.fullmatch(job_id) and access_store().job_seen(job_id):
                self.respond(410, {'error': 'This result has expired. Generate a new one.'})
            else:
                self.respond(404, {'error': 'Unknown job.'})
            return
        if len(parts) == 3:
            try:
                job = public_job(job_id, directory)
                process = JOB_PROCESSES.get(job_id)
                if (process is not None and process.poll() is not None and
                        job['status'] in ('starting', 'generating', 'plan_ready', 'enhanced_ready')):
                    job['status'] = 'failed'
                    job['message'] = 'The local workflow stopped before a final result was saved. Check the local log.'
                self.respond(200, job)
            except (OSError, ValueError, json.JSONDecodeError):
                self.respond(503, {'error': 'Result is being saved. Retry shortly.'})
            return
        if len(parts) != 4:
            self.respond(404, {'error': 'Not found.'})
            return
        report_path = directory / 'result.json'
        if not report_path.is_file():
            self.respond(404, {'error': 'Result is not ready.'})
            return
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if parts[3] == 'review':
            file = directory / 'review.html'
        elif parts[3] == 'inverse-scale-review':
            file = directory / 'inverse-scale-review.html'
        elif parts[3] == 'uploaded':
            file = directory / 'uploadedImage.png'
        elif parts[3] == 'original':
            file = directory / 'originalImage.png'
        elif parts[3] == 'after':
            name = ('enhancedImage.png' if report.get('enhancedImage') == 'enhancedImage.png' else
                    report.get('alignedCandidateImage') or report.get('candidateImage'))
            file = directory / name if name and Path(name).name == name else None
        else:
            file = None
        if not file or not file.is_file():
            self.respond(404, {'error': 'Image or review not available.'})
            return
        if parts[3] in ('review', 'inverse-scale-review'):
            visitor, _ = self.visitor()
            access_store().event('review_view', visitor, job_id=job_id)
        self.respond(200, file.read_bytes(), MIME[file.suffix],
                     review=parts[3] in ('review', 'inverse-scale-review'))

    def do_POST(self):
        if self.path != '/api/jobs':
            self.respond(404, {'error': 'Not found.'})
            return
        visitor, cookie = self.visitor()
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or not 0 < length <= MAX_REQUEST_BYTES:
            access_store().event('upload_rejected', visitor, detail='request_size_or_type')
            self.respond(413, {'error': 'Upload a JPEG or PNG smaller than 12 MB.'}, cookie=cookie)
            return
        try:
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError('Invalid upload request.')
            style = MakeupStyle(request.get('style') or 'Auto')
            photo = request.get('image')
            if not isinstance(photo, str):
                raise ValueError('Missing image.')
            raw = base64.b64decode(photo, validate=True)
            if not 0 < len(raw) <= MAX_IMAGE_BYTES:
                raise ValueError('Photo exceeds 12 MB.')
            from io import BytesIO
            with Image.open(BytesIO(raw)) as image:
                if image.format not in ('JPEG', 'PNG') or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Use one JPEG or PNG photo.')
                if image.width * image.height > 20_000_000:
                    raise ValueError('Photo dimensions are too large.')
                image.verify()
        except (ValueError, KeyError, TypeError, binascii.Error, UnidentifiedImageError, OSError) as exc:
            access_store().event('upload_rejected', visitor, detail='invalid_photo_or_style')
            self.respond(400, {'error': str(exc) or 'Invalid photo or style.'}, cookie=cookie)
            return
        job_id = uuid.uuid4().hex
        model = ROOT / 'models' / 'face_landmarker.task'
        if not model.is_file():
            self.respond(503, {'error': 'Face landmark model is unavailable.'}, cookie=cookie)
            return
        extension = '.jpg' if raw.startswith(b'\xff\xd8') else '.png'
        upload = UPLOADS / (job_id + extension)
        output = RUNS / job_id
        env = os.environ.copy()
        env['MPLCONFIGDIR'] = '/tmp/mpl'
        logs = UPLOADS / (job_id + '.log')
        with _JOB_START_LOCK:
            if PUBLIC_MODE and any(process.poll() is None for process in JOB_PROCESSES.values()):
                access_store().event('generation_busy', visitor)
                self.respond(503, {'error': 'A photo is being processed. Please try again shortly.',
                                   'code': 'SERVER_BUSY'}, cookie=cookie)
                return
            try:
                reason = access_store().reserve(visitor, job_id) if PUBLIC_MODE else None
            except (OSError, sqlite3.Error):
                self.respond(503, {'error': 'Usage limit service is unavailable. Please retry later.'}, cookie=cookie)
                return
            if reason:
                error = ('Your two tries for today are used up.' if reason == 'VISITOR_LIMIT'
                         else 'Today’s total of 20 tries has been reached.')
                self.respond(429, {'error': error, 'code': reason,
                                   'quota': access_store().remaining(visitor)}, cookie=cookie)
                return
            try:
                UPLOADS.mkdir(parents=True, exist_ok=True)
                RUNS.mkdir(parents=True, exist_ok=True)
                os.chmod(UPLOADS, 0o700)
                os.chmod(RUNS, 0o700)
                upload.write_bytes(raw)
                os.chmod(upload, 0o600)
                with logs.open('wb') as log:
                    process = subprocess.Popen([sys.executable, '-m', 'makeup_refine.cli', str(upload),
                        '--output', str(output), '--style', style.value,
                        '--landmark-model', str(model), '--vision-model', 'gpt-4.1-mini',
                        '--edit-model', 'gpt-image-2', '--max-edit-attempts', '1'],
                        cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                        start_new_session=True)
                    JOB_PROCESSES[job_id] = process
            except OSError:
                upload.unlink(missing_ok=True)
                logs.unlink(missing_ok=True)
                if PUBLIC_MODE:
                    access_store().release(visitor, job_id)
                else:
                    access_store().event('generation_start_failed', visitor, job_id=job_id)
                self.respond(503, {'error': 'Could not start the image workflow.'}, cookie=cookie)
                return
        if not PUBLIC_MODE:
            access_store().event('generation_accepted', visitor, job_id=job_id, detail=style.value)
        self.respond(202, {'id': job_id, 'status': 'starting'}, cookie=cookie)


def main():
    parser = argparse.ArgumentParser(description='Run makeup web page')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8765')))
    args = parser.parse_args()
    if PUBLIC_MODE:
        if not os.environ.get('MAKEUP_VISITOR_SECRET') or not os.environ.get('MAKEUP_STATE_DB'):
            parser.error('Public mode requires MAKEUP_VISITOR_SECRET and a persistent MAKEUP_STATE_DB.')
        state_parent, temp_path = STATE_DB.parent.resolve(), TEMP_ROOT.resolve()
        if (not os.environ.get('MAKEUP_TEMP_DIR') or state_parent == temp_path or
                state_parent in temp_path.parents or temp_path in state_parent.parents):
            parser.error('Public mode requires a separate temporary directory for photos.')
        if not os.environ.get('OPENAI_API_KEY'):
            parser.error('Public mode requires OPENAI_API_KEY in the service environment.')
    access_store()
    if PUBLIC_MODE:
        threading.Thread(target=cleanup_loop, daemon=True, name='temporary-image-cleanup').start()
    server = ThreadingHTTPServer((args.host, args.port), WebHandler)
    print(f'Open http://{args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
