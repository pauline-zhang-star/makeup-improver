from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os

from makeup_refine.public_guard import AccessStore
from makeup_refine import web_app


def instant(day):
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def test_signed_visitor_cookie_and_daily_reset(tmp_path):
    store = AccessStore(tmp_path / 'state.sqlite3', 'test-secret', 2, 20)
    visitor, signed = store.visitor('')
    assert signed and store.visitor(f'mirror_vid={signed}')[0] == visitor
    assert store.visitor(f'mirror_vid={signed}bad')[0] != visitor
    assert store.reserve(visitor, 'a' * 32, instant('2026-10-02')) is None
    assert store.reserve(visitor, 'b' * 32, instant('2026-10-02')) is None
    assert store.reserve(visitor, 'c' * 32, instant('2026-10-02')) == 'VISITOR_LIMIT'
    assert store.remaining(visitor, instant('2026-10-02'))['visitorRemaining'] == 0
    assert store.reserve(visitor, 'd' * 32, instant('2026-10-03')) is None
    with store.connect() as db:
        row = db.execute('SELECT event,visitor_hash,job_id FROM access_events LIMIT 1').fetchone()
    assert row[1] != visitor and row[2] == 'a' * 32


def test_global_limit_is_atomic_across_concurrent_visitors(tmp_path):
    store = AccessStore(tmp_path / 'state.sqlite3', 'test-secret', 2, 50)
    now = instant('2026-10-02')
    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(lambda i: store.reserve(f'visitor-{i}', f'{i:032x}', now), range(64)))
    assert outcomes.count(None) == 50
    assert outcomes.count('DAILY_LIMIT') == 14
    assert store.remaining('new-visitor', now)['dailyRemaining'] == 0


def test_refund_is_idempotent_and_uses_reservation_day(tmp_path):
    store = AccessStore(tmp_path / 'state.sqlite3', 'test-secret')
    before_midnight = instant('2026-10-02')
    next_day = instant('2026-10-03')
    assert store.reserve('visitor', 'a' * 32, before_midnight) is None
    assert store.release('visitor', 'a' * 32, next_day) is True
    assert store.release('visitor', 'a' * 32, next_day) is False
    assert store.remaining('visitor', before_midnight)['visitorRemaining'] == 2
    assert store.remaining('visitor', before_midnight)['dailyRemaining'] == 50


def test_temporary_images_and_results_expire_without_touching_metadata(tmp_path, monkeypatch):
    uploads, runs = tmp_path / 'uploads', tmp_path / 'runs'
    uploads.mkdir(); runs.mkdir()
    job_id = 'a' * 32
    upload = uploads / f'{job_id}.png'
    upload.write_bytes(b'photo')
    result = runs / job_id
    result.mkdir()
    (result / 'result.json').write_text(json.dumps({'status': 'completed'}))
    old = 1_600_000_000
    os.utime(upload, (old, old))
    os.utime(result, (old, old))
    state = tmp_path / 'state.sqlite3'
    state.write_text('metadata')
    monkeypatch.setattr(web_app, 'UPLOADS', uploads)
    monkeypatch.setattr(web_app, 'RUNS', runs)
    monkeypatch.setattr(web_app, 'JOB_PROCESSES', {})
    web_app.cleanup_expired()
    assert not upload.exists() and not result.exists()
    assert state.read_text() == 'metadata'
