"""Single-request, photo-free-after-response adapter for Vercel Docker Functions."""
import argparse
import base64
import binascii
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .api_usage import no_provider_calls
from .look_models import MakeupStyle
from .redis_guard import RedisGuard
from .guidance_ticket import issue, verify, evidence_for_display, TTL
from .upload_format import UPLOAD_SUFFIXES, validate_upload
from .web_app import ASSETS, MIME, ROOT, WebHandler, public_job


MAX_REQUEST_BYTES = 4_100_000
MAX_IMAGE_BYTES = 3_000_000
MAX_RESULT_IMAGE_BYTES = 2_200_000
_GUARD = None


def guard():
    global _GUARD
    if _GUARD is None:
        _GUARD = RedisGuard.from_environment()
    return _GUARD


def compact_jpeg(path, max_bytes=MAX_RESULT_IMAGE_BYTES):
    """Keep the single response below Vercel's 4.5 MB payload limit."""
    with Image.open(path) as source:
        image = source.convert('RGB')
        for max_edge in (1800, 1600, 1400, 1200, 1000, 800):
            if max(image.size) > max_edge:
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            for quality in (88, 80, 72):
                stream = BytesIO()
                image.save(stream, format='JPEG', quality=quality, optimize=True)
                if stream.tell() <= max_bytes:
                    return 'data:image/jpeg;base64,' + base64.b64encode(stream.getvalue()).decode()
    raise ValueError('The generated image is too large to display on this free service.')


def compact_matched_pair(original_path, enhanced_path, original_budget=800_000,
                         enhanced_budget=MAX_RESULT_IMAGE_BYTES):
    """Encode a before/after pair at one shared size for an aligned slider."""
    with Image.open(original_path) as before_source, Image.open(enhanced_path) as after_source:
        before = before_source.convert('RGB')
        after = after_source.convert('RGB')
    if before.size != after.size:
        raise ValueError('The accepted images do not have matching dimensions.')
    for max_edge in (1800, 1600, 1400, 1200, 1000, 800):
        if max(before.size) > max_edge:
            before.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            after.thumbnail(before.size, Image.Resampling.LANCZOS)
        encoded = []
        for image, budget in ((before, original_budget), (after, enhanced_budget)):
            data = None
            for quality in (88, 80, 72):
                stream = BytesIO()
                image.save(stream, format='JPEG', quality=quality, optimize=True)
                if stream.tell() <= budget:
                    data = stream.getvalue()
                    break
            encoded.append(data)
        if all(encoded):
            return tuple('data:image/jpeg;base64,' + base64.b64encode(data).decode()
                         for data in encoded)
    raise ValueError('The generated images are too large to display on this free service.')


def display_image_file(directory):
    report = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
    for name in (report.get('enhancedImage'), report.get('alignedCandidateImage'),
                 report.get('candidateImage')):
        if name and Path(name).name == name and (directory / name).is_file():
            return directory / name
    return None


def timeout_metadata(directory):
    """Summarize persisted workflow state without reading photo or prompt content."""
    result = {}
    try:
        result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    calls = []
    try:
        usage = json.loads((directory / 'api-usage.json').read_text(encoding='utf-8'))
        calls = usage.get('calls', []) if isinstance(usage, dict) else []
    except (OSError, ValueError):
        pass
    calls = calls if isinstance(calls, list) else []
    active_call = next((call for call in reversed(calls)
                        if isinstance(call, dict) and call.get('status') == 'in_flight'), None)
    stage = active_call.get('stage') if active_call else None
    if stage not in {'planning', 'generation', 'comparison'}:
        generation_returned = any(isinstance(call, dict) and
                                  call.get('stage') == 'generation' and
                                  call.get('status') == 'response_received' for call in calls)
        stage = ('comparison' if result.get('status') == 'enhanced_ready'
                 else 'review' if generation_returned or result.get('candidateImage')
                 else 'generation_preparation' if result.get('techniquePlan')
                 else 'preflight' if not calls else 'unknown')
    working_size = (result.get('inputCrop') or {}).get('workingSize')
    if not working_size and (directory / 'originalImage.png').is_file():
        try:
            with Image.open(directory / 'originalImage.png') as original:
                working_size = list(original.size)
        except OSError:
            pass
    return {'stage': stage, 'providerCallsStarted': len(calls),
            'apiRequestActive': active_call is not None, 'workingSize': working_size,
            'enhancedReady': (result.get('status') == 'enhanced_ready'
                              and (directory / 'enhancedImage.png').is_file())}


class VercelHandler(WebHandler):
    server_version = 'MakeupRefineVercel/1.0'

    def serve_job(self, job_id, output, cookie, status_override=None, started_at=None):
        job = public_job(job_id, output)
        if job['afterUrl']:
            image_file = display_image_file(output)
            if image_file is None:
                raise ValueError('No displayed image exists.')
            original_file = output / 'originalImage.png'
            if job['originalUrl'] and not job['diagnostic']:
                job['originalUrl'], job['afterUrl'] = compact_matched_pair(
                    original_file, image_file, original_budget=450_000,
                    enhanced_budget=1_200_000)
            else:
                # Rejected diagnostic candidates may be returned at an unrelated
                # size. Keep both visible without presenting them as accepted.
                job['afterUrl'] = compact_jpeg(image_file)
                if job['originalUrl']:
                    job['originalUrl'] = compact_jpeg(original_file, 800_000)
        job['uploadedUrl'] = None
        job['reviewUrl'] = None
        if status_override:
            job.update(status_override)
        if job['status'] == 'preview_ready':
            report = json.loads((output / 'result.json').read_text())
            visitor, _ = (guard().visitor(guard().cookie_header(cookie, True))
                          if cookie else self.visitor())
            job['guidanceToken'] = issue(guard().secret, visitor, job_id, report,
                                         job['originalUrl'], job['afterUrl'])
            job['steps'] = []; job['callouts'] = []; job['plannedGuides'] = []
        if started_at is not None:
            job['serverDurationSeconds'] = round(time.perf_counter() - started_at, 1)
            api_seconds = sum(job.get('apiTiming', {}).values()) / 1000
            job['nonAPIDurationSeconds'] = round(max(0., job['serverDurationSeconds'] - api_seconds), 1)
        self.respond(200, job, cookie=cookie)

    def visitor(self):
        return guard().visitor(self.headers.get('Cookie', ''))

    def respond(self, status, data, content_type='application/json; charset=utf-8',
                review=False, cookie=None):
        # Vercel serves the public domain over HTTPS, even though its container
        # proxy connects to this internal HTTP listener.
        if cookie:
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, (dict, list)) else data
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Set-Cookie', RedisGuard.cookie_header(cookie, True))
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; "
                             "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)
            return
        super().respond(status, data, content_type, review, cookie)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/health':
            self.respond(200, {'ok': True})
        elif path == '/api/quota':
            try:
                visitor, cookie = self.visitor()
                self.respond(200, {'limited': True, 'mode': 'serverless',
                                   'dailyLimit': guard().daily_limit,
                                   **guard().remaining(visitor)}, cookie=cookie)
            except Exception:
                self.respond(503, {'error': 'Usage limit service is unavailable.'})
        elif path in ('/', '/app.js', '/style.css'):
            name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
            cookie = None
            if path == '/':
                try:
                    visitor, cookie = self.visitor()
                    guard().event('page_view', visitor)
                except Exception:
                    cookie = None
            self.respond(200, (ASSETS / name).read_bytes(), MIME[Path(name).suffix], cookie=cookie)
        else:
            self.respond(404, {'error': 'Not found.'})

    def do_POST(self):
        started_at = time.perf_counter()
        if self.path == '/api/guidance':
            self.generate_guidance()
            return
        if self.path != '/api/generate':
            self.respond(404, {'error': 'Not found.'})
            return
        try:
            visitor, cookie = self.visitor()
        except Exception:
            self.respond(503, {'error': 'Usage limit service is unavailable.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if (self.headers.get('Content-Type', '').split(';')[0] != 'application/json'
                    or not 0 < length <= MAX_REQUEST_BYTES):
                self.respond(413, {'error': 'This photo is too large for the free service.'}, cookie=cookie)
                return
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError('Invalid request.')
            style = MakeupStyle(request.get('style') or 'Auto')
            photo = request.get('image')
            if not isinstance(photo, str):
                raise ValueError('Missing image.')
            raw = base64.b64decode(photo, validate=True)
            if not 0 < len(raw) <= MAX_IMAGE_BYTES:
                raise ValueError('Photo exceeds the free service upload limit.')
            input_format = validate_upload(raw)
        except (ValueError, KeyError, TypeError, binascii.Error, UnidentifiedImageError, OSError) as exc:
            try:
                guard().event('upload_rejected', visitor, detail='invalid_photo_or_style')
            except Exception:
                pass
            self.respond(400, {'error': str(exc) or 'Invalid photo or style.'}, cookie=cookie)
            return
        model = ROOT / 'models' / 'face_landmarker.task'
        if not model.is_file() or not os.environ.get('OPENAI_API_KEY'):
            self.respond(503, {'error': 'Image service is not configured.'}, cookie=cookie)
            return
        job_id = uuid.uuid4().hex
        try:
            reason = guard().reserve(visitor, job_id)
        except Exception:
            self.respond(503, {'error': 'Usage limit service is unavailable.'}, cookie=cookie)
            return
        if reason:
            self.respond(429, {'error': 'Daily generation limit reached.', 'code': reason}, cookie=cookie)
            return

        with tempfile.TemporaryDirectory(prefix='makeup-', dir='/tmp') as temporary:
            directory = Path(temporary)
            upload = directory / ('upload' + UPLOAD_SUFFIXES[input_format])
            output = directory / 'result'
            upload.write_bytes(raw)
            os.chmod(upload, 0o600)
            env = os.environ.copy()
            env['MPLCONFIGDIR'] = '/tmp/mpl'
            env['MAKEUP_DIAGNOSTICS'] = '1'
            env['MAKEUP_SKIP_REVIEW_HTML'] = '1'
            command = [sys.executable, '-m', 'makeup_refine.cli', str(upload),
                       '--output', str(output), '--style', style.value,
                       '--landmark-model', str(model), '--vision-model', 'gpt-4.1-mini',
                       '--edit-model', 'gpt-image-2', '--max-edit-attempts', '1',
                       '--max-working-edge', '1536', '--defer-guidance']
            try:
                completed = subprocess.run(command, cwd=ROOT, env=env,
                                           stdin=subprocess.DEVNULL, capture_output=True,
                                           timeout=270, check=False)
            except OSError:
                guard().release(visitor, job_id)
                self.respond(503, {'error': 'Could not start image generation.'}, cookie=cookie)
                return
            except subprocess.TimeoutExpired:
                diagnostics = timeout_metadata(output)
                refunded = no_provider_calls(output)
                if refunded:
                    guard().release(visitor, job_id)
                size = diagnostics['workingSize'] or ['?', '?']
                detail = (f"{diagnostics['stage']}:{diagnostics['providerCallsStarted']}:"
                          f"{'api_active' if diagnostics['apiRequestActive'] else 'local'}:"
                          f"{size[0]}x{size[1]}")
                print('makeup_generation_timeout', detail, flush=True)
                guard().event('generation_timeout', visitor, job_id=job_id, detail=detail)
                if diagnostics['enhancedReady']:
                    try:
                        self.serve_job(job_id, output, cookie, {
                            'status': 'instructions_unavailable',
                            'message': 'The enhanced image passed local checks, but the makeup-step comparison timed out.',
                            'timeoutStage': diagnostics['stage'],
                            'providerCallsStarted': diagnostics['providerCallsStarted'],
                            'plannedGuides': [], 'callouts': [],
                        }, started_at=started_at)
                        return
                    except (OSError, ValueError, json.JSONDecodeError):
                        pass
                self.respond(504, {'error': 'Generation exceeded the free service time limit.',
                                   'code': 'GENERATION_TIMEOUT',
                                   'stage': diagnostics['stage'],
                                   'providerCallsStarted': diagnostics['providerCallsStarted'],
                                   'apiRequestActive': diagnostics['apiRequestActive'],
                                   'workingSize': diagnostics['workingSize'],
                                   'quotaRefunded': refunded}, cookie=cookie)
                return

            result_file = output / 'result.json'
            if no_provider_calls(output):
                guard().release(visitor, job_id)
            if not result_file.is_file():
                # No report means failure happened before a provider was created.
                # Native MediaPipe errors are otherwise lost with the /tmp worker.
                print('makeup_preflight_failure', completed.returncode,
                      completed.stderr.decode(errors='replace')[-1800:], flush=True)
                guard().event('generation_failed', visitor, job_id=job_id,
                              detail=f'worker_exit_{completed.returncode}')
                self.respond(502, {'error': 'The image workflow stopped before saving a result.'}, cookie=cookie)
                return
            try:
                job = public_job(job_id, output)
                guard().event('generation_finished', visitor, job_id=job_id, detail=job['status'])
                self.serve_job(job_id, output, cookie, started_at=started_at)
            except (OSError, ValueError, json.JSONDecodeError):
                guard().event('result_unavailable', visitor, job_id=job_id)
                self.respond(502, {'error': 'The generated result could not be displayed.'}, cookie=cookie)


    def generate_guidance(self):
        cookie = None
        lock = None
        try:
            visitor, cookie = self.visitor()
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json' or not 0 < length <= MAX_REQUEST_BYTES:
                raise ValueError('Instructions request is too large.')
            request = json.loads(self.rfile.read(length))
            before, after = request.get('originalUrl'), request.get('afterUrl')
            ticket = verify(guard().secret, visitor, request.get('guidanceToken'), before, after)
            job_id = ticket['id']
            cache_key = 'makeup:guidance:' + job_id
            cached = guard().command('GET', cache_key)
            if cached:
                job = json.loads(cached)
                job.update(originalUrl=before, afterUrl=after)
                self.respond(200, job, cookie=cookie)
                return
            lock_key = cache_key + ':lock'
            if not guard().command('SET', lock_key, '1', 'NX', 'EX', 180):
                self.respond(409, {'error': 'Instructions are already being prepared. Try again shortly.'}, cookie=cookie)
                return
            lock = lock_key
            attempts_key = cache_key + ':attempts'
            attempts = int(guard().command('INCR', attempts_key))
            guard().command('EXPIRE', attempts_key, TTL)
            if attempts > 2:
                self.respond(429, {'error': 'Instructions retry limit reached for this preview.'}, cookie=cookie)
                return
            with tempfile.TemporaryDirectory(prefix='makeup-guidance-', dir='/tmp') as temporary:
                output = Path(temporary)
                for name, url in [('originalImage.png', before), ('enhancedImage.png', after)]:
                    if not url.startswith('data:image/jpeg;base64,'):
                        raise ValueError('Invalid preview image.')
                    raw = base64.b64decode(url.split(',', 1)[1], validate=True)
                    with Image.open(BytesIO(raw)) as image:
                        if max(image.size) > 1800:
                            raise ValueError('Invalid preview dimensions.')
                        image.convert('RGB').save(output / name, compress_level=1)
                        display_size = image.size
                report = ticket['report']
                report['comparisonEvidence'] = evidence_for_display(report.get('comparisonEvidence'), display_size)
                report.update(status='preview_ready', originalImage='originalImage.png',
                              enhancedImage='enhancedImage.png', steps=[])
                (output / 'result.json').write_text(json.dumps(report))
                env = os.environ.copy()
                env['MAKEUP_SKIP_REVIEW_HTML'] = '1'
                command = [sys.executable, '-m', 'makeup_refine.cli', '--retry-instructions',
                           str(output), '--vision-model', 'gpt-4.1-mini']
                subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=120, check=False)
                job = public_job(job_id, output)
                job.update(originalUrl=before, afterUrl=after, reviewUrl=None, uploadedUrl=None)
                if job['status'] == 'preview_ready':
                    raise RuntimeError('Instructions could not be verified. Please try again.')
                if job['status'] != 'instructions_unavailable':
                    saved = {k: v for k, v in job.items() if k not in ('originalUrl', 'afterUrl')}
                    guard().command('SET', cache_key, json.dumps(saved), 'EX', TTL)
                self.respond(200, job, cookie=cookie)
        except (ValueError, binascii.Error, UnidentifiedImageError) as exc:
            self.respond(400, {'error': str(exc)}, cookie=cookie)
        except Exception:
            self.respond(503, {'error': 'Instructions could not be prepared. Your preview is still available.'}, cookie=cookie)
        finally:
            if lock:
                try:
                    guard().command('DEL', lock)
                except Exception:
                    pass


def main():
    parser = argparse.ArgumentParser(description='Run the stateless Vercel makeup service')
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8765')))
    args = parser.parse_args()
    # Refuse to expose an unguarded generation endpoint.
    if not os.environ.get('OPENAI_API_KEY') or not (ROOT / 'models' / 'face_landmarker.task').is_file():
        parser.error('OPENAI_API_KEY and the landmark model are required.')
    guard()
    server = ThreadingHTTPServer((args.host, args.port), VercelHandler)
    server.serve_forever()


if __name__ == '__main__':
    main()
