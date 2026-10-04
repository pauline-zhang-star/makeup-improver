"""Single-request, photo-free-after-response adapter for Vercel Docker Functions."""
import argparse
import base64
import binascii
import json
import os
import subprocess
import sys
import tempfile
import uuid
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .api_usage import no_provider_calls
from .look_models import MakeupStyle
from .redis_guard import RedisGuard
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


def display_image_file(directory):
    report = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
    for name in (report.get('enhancedImage'), report.get('alignedCandidateImage'),
                 report.get('candidateImage')):
        if name and Path(name).name == name and (directory / name).is_file():
            return directory / name
    return None


class VercelHandler(WebHandler):
    server_version = 'MakeupRefineVercel/1.0'

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
            command = [sys.executable, '-m', 'makeup_refine.cli', str(upload),
                       '--output', str(output), '--style', style.value,
                       '--landmark-model', str(model), '--vision-model', 'gpt-4.1-mini',
                       '--edit-model', 'gpt-image-2', '--max-edit-attempts', '1']
            try:
                completed = subprocess.run(command, cwd=ROOT, env=env,
                                           stdin=subprocess.DEVNULL, capture_output=True,
                                           timeout=270, check=False)
            except OSError:
                guard().release(visitor, job_id)
                self.respond(503, {'error': 'Could not start image generation.'}, cookie=cookie)
                return
            except subprocess.TimeoutExpired:
                if no_provider_calls(output):
                    guard().release(visitor, job_id)
                guard().event('generation_timeout', visitor, job_id=job_id)
                self.respond(504, {'error': 'Generation exceeded the free service time limit.'}, cookie=cookie)
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
                if job['afterUrl']:
                    image_file = display_image_file(output)
                    if image_file is None:
                        raise ValueError('No displayed image exists.')
                    job['afterUrl'] = compact_jpeg(image_file)
                    if job['originalUrl'] and input_format == 'HEIF':
                        job['originalUrl'] = compact_jpeg(output / 'originalImage.png', 800_000)
                    else:
                        job['originalUrl'] = 'client:original' if job['originalUrl'] else None
                job['uploadedUrl'] = None
                job['reviewUrl'] = None
                guard().event('generation_finished', visitor, job_id=job_id, detail=job['status'])
                self.respond(200, job, cookie=cookie)
            except (OSError, ValueError, json.JSONDecodeError):
                guard().event('result_unavailable', visitor, job_id=job_id)
                self.respond(502, {'error': 'The generated result could not be displayed.'}, cookie=cookie)


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
