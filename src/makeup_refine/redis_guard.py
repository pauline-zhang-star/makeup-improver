"""Atomic anonymous quotas and photo-free access events for Vercel."""
import json
import os
from datetime import datetime, timezone

import httpx

from .public_guard import SignedVisitors, next_utc_day, utc_day


RESERVE_SCRIPT = '''
local visitor = tonumber(redis.call('GET', KEYS[1]) or '0')
local daily = tonumber(redis.call('GET', KEYS[2]) or '0')
local reason = 0
if visitor >= tonumber(ARGV[1]) then reason = 1
elseif daily >= tonumber(ARGV[2]) then reason = 2
else
  redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], 172800)
  redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], 172800)
  redis.call('SET', KEYS[3], '1', 'EX', 172800)
end
redis.call('LPUSH', KEYS[4], ARGV[3] .. ':' .. reason)
redis.call('LTRIM', KEYS[4], 0, 999)
redis.call('EXPIRE', KEYS[4], 2678400)
return reason
'''

RELEASE_SCRIPT = '''
if redis.call('DEL', KEYS[3]) == 1 then
  if tonumber(redis.call('GET', KEYS[1]) or '0') > 0 then redis.call('DECR', KEYS[1]) end
  if tonumber(redis.call('GET', KEYS[2]) or '0') > 0 then redis.call('DECR', KEYS[2]) end
  redis.call('LPUSH', KEYS[4], ARGV[1])
  redis.call('LTRIM', KEYS[4], 0, 999)
  redis.call('EXPIRE', KEYS[4], 2678400)
  return 1
end
return 0
'''

LOG_SCRIPT = '''
redis.call('LPUSH', KEYS[1], ARGV[1])
redis.call('LTRIM', KEYS[1], 0, 999)
redis.call('EXPIRE', KEYS[1], 2678400)
return 1
'''


class RedisGuard(SignedVisitors):
    def __init__(self, secret, url, token, visitor_limit=2, daily_limit=20, client=None):
        super().__init__(secret)
        if not url or not token or visitor_limit < 1 or daily_limit < 1:
            raise ValueError('Upstash credentials and positive quota limits are required.')
        if not url.startswith('https://'):
            raise ValueError('Upstash REST URL must use HTTPS.')
        self.url = url.rstrip('/')
        self.token = token
        self.visitor_limit = visitor_limit
        self.daily_limit = daily_limit
        self.client = client or httpx.Client(timeout=8)

    @classmethod
    def from_environment(cls):
        return cls(
            os.environ.get('MAKEUP_VISITOR_SECRET'),
            os.environ.get('UPSTASH_REDIS_REST_URL') or os.environ.get('KV_REST_API_URL'),
            os.environ.get('UPSTASH_REDIS_REST_TOKEN') or os.environ.get('KV_REST_API_TOKEN'),
            int(os.environ.get('MAKEUP_VISITOR_DAILY_LIMIT', '2')),
            int(os.environ.get('MAKEUP_GLOBAL_DAILY_LIMIT', '20')),
        )

    def command(self, *parts):
        response = self.client.post(self.url, json=list(parts),
                                    headers={'Authorization': f'Bearer {self.token}'})
        response.raise_for_status()
        payload = response.json()
        if 'error' in payload or 'result' not in payload:
            raise RuntimeError('Quota store rejected a command.')
        return payload['result']

    def keys(self, visitor, job_id, now):
        day = utc_day(now)
        identity = self.digest('visitor:' + visitor)
        return (f'makeup:q:{day}:v:{identity}', f'makeup:q:{day}:all',
                f'makeup:reservation:{job_id}', f'makeup:events:{day}')

    def remaining(self, visitor, now=None):
        instant = now or datetime.now(timezone.utc)
        visitor_key, daily_key, _, _ = self.keys(visitor, '-', instant)
        values = self.command('MGET', visitor_key, daily_key)
        if not isinstance(values, list) or len(values) != 2:
            raise RuntimeError('Invalid quota response.')
        used_visitor, used_daily = [int(value or 0) for value in values]
        return {'visitorRemaining': max(0, self.visitor_limit - used_visitor),
                'dailyRemaining': max(0, self.daily_limit - used_daily),
                'resetAt': next_utc_day(instant)}

    def reserve(self, visitor, job_id, now=None):
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        keys = self.keys(visitor, job_id, instant)
        event = json.dumps({'at': instant.isoformat(), 'event': 'generation_start',
                            'visitor': self.digest('visitor:' + visitor)[:24],
                            'job': job_id}, separators=(',', ':'))
        code = int(self.command('EVAL', RESERVE_SCRIPT, 4, *keys,
                                self.visitor_limit, self.daily_limit, event))
        return {0: None, 1: 'VISITOR_LIMIT', 2: 'DAILY_LIMIT'}[code]

    def release(self, visitor, job_id, now=None):
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        event = json.dumps({'at': instant.isoformat(), 'event': 'generation_start_failed',
                            'visitor': self.digest('visitor:' + visitor)[:24],
                            'job': job_id}, separators=(',', ':'))
        return self.command('EVAL', RELEASE_SCRIPT, 4,
                            *self.keys(visitor, job_id, instant), event)

    def event(self, name, visitor, job_id=None, detail=None, now=None):
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        payload = {'at': instant.isoformat(), 'event': name,
                   'visitor': self.digest('visitor:' + visitor)[:24]}
        if job_id:
            payload['job'] = job_id
        if detail:
            payload['detail'] = detail
        key = f'makeup:events:{utc_day(instant)}'
        self.command('EVAL', LOG_SCRIPT, 1, key,
                     json.dumps(payload, separators=(',', ':')))
