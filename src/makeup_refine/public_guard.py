"""Persistent anonymous visitor quotas and metadata-only access events."""
import argparse
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.cookies import CookieError, SimpleCookie
from pathlib import Path


COOKIE_NAME = 'mirror_vid'
EVENT_RETENTION_DAYS = 30


def utc_day(now=None):
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()


def next_utc_day(now=None):
    day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    return datetime.combine(day + timedelta(days=1), datetime.min.time(), timezone.utc).isoformat()


class AccessStore:
    def __init__(self, path: Path, secret: str, visitor_limit=2, daily_limit=20):
        if not secret or visitor_limit < 1 or daily_limit < 1:
            raise ValueError('A secret and positive daily limits are required.')
        self.path = Path(path)
        self.secret = secret.encode('utf-8')
        self.visitor_limit = visitor_limit
        self.daily_limit = daily_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS daily_quota (
                  day TEXT NOT NULL, scope TEXT NOT NULL, subject TEXT NOT NULL,
                  used INTEGER NOT NULL, PRIMARY KEY(day, scope, subject));
                CREATE TABLE IF NOT EXISTS access_events (
                  id INTEGER PRIMARY KEY, at_utc TEXT NOT NULL, event TEXT NOT NULL,
                  visitor_hash TEXT NOT NULL, job_id TEXT, detail TEXT);
                CREATE INDEX IF NOT EXISTS access_events_at ON access_events(at_utc);
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA busy_timeout=10000')
            with db:
                yield db
        finally:
            db.close()

    def digest(self, value):
        return hmac.new(self.secret, value.encode('utf-8'), hashlib.sha256).hexdigest()

    def visitor(self, cookie_header):
        jar = SimpleCookie()
        try:
            jar.load(cookie_header or '')
            signed = jar[COOKIE_NAME].value if COOKIE_NAME in jar else ''
            value, signature = signed.split('.', 1)
            if (len(value) == 32 and len(signature) == 64
                    and all(c in '0123456789abcdef' for c in value)
                    and hmac.compare_digest(signature, self.digest('cookie:' + value))):
                return value, None
        except (ValueError, IndexError, CookieError):
            pass
        value = secrets.token_hex(16)
        return value, f'{value}.{self.digest("cookie:" + value)}'

    @staticmethod
    def cookie_header(signed, secure):
        return (f'{COOKIE_NAME}={signed}; Path=/; Max-Age=31536000; '
                f'HttpOnly; SameSite=Lax' + ('; Secure' if secure else ''))

    def remaining(self, visitor, now=None):
        day = utc_day(now)
        subject = self.digest('visitor:' + visitor)
        with self.connect() as db:
            values = {scope: (db.execute(
                'SELECT used FROM daily_quota WHERE day=? AND scope=? AND subject=?',
                (day, scope, key)).fetchone() or [0])[0]
                for scope, key in [('visitor', subject), ('global', '*')]}
        return {'visitorRemaining': max(0, self.visitor_limit - values['visitor']),
                'dailyRemaining': max(0, self.daily_limit - values['global']),
                'resetAt': next_utc_day(now)}

    def job_seen(self, job_id):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM access_events WHERE job_id=? LIMIT 1',
                              (job_id,)).fetchone() is not None

    def event(self, name, visitor, job_id=None, detail=None, now=None):
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self.connect() as db:
            db.execute('INSERT INTO access_events(at_utc,event,visitor_hash,job_id,detail) '
                       'VALUES(?,?,?,?,?)', (instant.isoformat(), name,
                       self.digest('visitor:' + visitor), job_id, detail))
            self._prune(db, instant)

    @staticmethod
    def _prune(db, instant):
        db.execute('DELETE FROM access_events WHERE at_utc < ?',
                   ((instant - timedelta(days=EVENT_RETENTION_DAYS)).isoformat(),))
        db.execute('DELETE FROM daily_quota WHERE day < ?',
                   ((instant.date() - timedelta(days=7)).isoformat(),))

    def prune(self):
        with self.connect() as db:
            self._prune(db, datetime.now(timezone.utc))

    def reserve(self, visitor, job_id, now=None):
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        day = utc_day(instant)
        subject = self.digest('visitor:' + visitor)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            counts = {scope: (db.execute(
                'SELECT used FROM daily_quota WHERE day=? AND scope=? AND subject=?',
                (day, scope, key)).fetchone() or [0])[0]
                for scope, key in [('visitor', subject), ('global', '*')]}
            reason = ('VISITOR_LIMIT' if counts['visitor'] >= self.visitor_limit else
                      'DAILY_LIMIT' if counts['global'] >= self.daily_limit else None)
            if not reason:
                for scope, key in [('visitor', subject), ('global', '*')]:
                    db.execute('INSERT INTO daily_quota(day,scope,subject,used) VALUES(?,?,?,1) '
                               'ON CONFLICT(day,scope,subject) DO UPDATE SET used=used+1',
                               (day, scope, key))
            db.execute('INSERT INTO access_events(at_utc,event,visitor_hash,job_id,detail) '
                       'VALUES(?,?,?,?,?)', (instant.isoformat(),
                       'generation_blocked' if reason else 'generation_accepted',
                       subject, job_id if not reason else None, reason))
            self._prune(db, instant)
        return reason

    def release(self, visitor, job_id, now=None):
        """Undo a reservation only if the local workflow never started."""
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        day = utc_day(instant)
        subject = self.digest('visitor:' + visitor)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for scope, key in [('visitor', subject), ('global', '*')]:
                db.execute('UPDATE daily_quota SET used=MAX(0,used-1) '
                           'WHERE day=? AND scope=? AND subject=?', (day, scope, key))
            db.execute('INSERT INTO access_events(at_utc,event,visitor_hash,job_id,detail) '
                       'VALUES(?,?,?,?,?)', (instant.isoformat(), 'generation_start_failed',
                       subject, job_id, None))


def main():
    parser = argparse.ArgumentParser(description='Read metadata-only makeup access events')
    parser.add_argument('--db', type=Path, default=os.environ.get('MAKEUP_STATE_DB'))
    parser.add_argument('--last', type=int, default=30)
    args = parser.parse_args()
    if args.db is None or not args.db.is_file():
        parser.error('Specify an existing --db or MAKEUP_STATE_DB.')
    with sqlite3.connect(args.db) as db:
        totals = db.execute('SELECT substr(at_utc,1,10),event,count(*) FROM access_events '
                            'GROUP BY 1,2 ORDER BY 1 DESC,2').fetchall()
        recent = db.execute('SELECT at_utc,event,substr(visitor_hash,1,12),job_id,detail '
                            'FROM access_events ORDER BY id DESC LIMIT ?',
                            (max(0, min(args.last, 500)),)).fetchall()
    print(json.dumps({'dailyEvents': totals, 'recentEvents': recent}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
