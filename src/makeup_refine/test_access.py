"""Temporary invitation-only beta access: shared ten attempts, seven days.

Independent of Apple purchases, disabled unless a code digest is configured.
No device identifier or reusable bypass is embedded in the app.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from .subscriptions import SubscriptionError

LIMIT = 10
DURATION = 7 * 86400
RESERVE = '''
local r = cjson.decode(redis.call('GET', KEYS[1]) or '{}')
if not r.expiresAt or tonumber(r.expiresAt) <= tonumber(ARGV[1]) then return 'TEST_ACCESS_EXPIRED' end
if redis.call('EXISTS', KEYS[3]) == 1 then return 'DUPLICATE_REQUEST' end
if tonumber(redis.call('GET', KEYS[2]) or '0') >= 10 then return 'TEST_LIMIT_REACHED' end
redis.call('INCR', KEYS[2])
redis.call('SET', KEYS[3], 'used', 'EX', 604800)
return 'OK'
'''
REFUND = '''
if redis.call('GET', KEYS[2]) ~= 'used' then return 0 end
redis.call('SET', KEYS[2], 'refunded', 'EX', 604800)
if tonumber(redis.call('GET', KEYS[1]) or '0') > 0 then redis.call('DECR', KEYS[1]) end
return 1
'''

class TestAccess:
    __test__ = False
    def __init__(self, store, digest=None, clock=time.time):
        self.store, self.clock = store, clock
        self.digest = digest if digest is not None else os.environ.get('MAKEUP_TEST_CODE_SHA256', '')

    def enabled(self):
        if not re.fullmatch('[a-f0-9]{64}', self.digest):
            raise SubscriptionError('测试权限暂未开启 / Test access is unavailable.', 'TEST_ACCESS_DISABLED', 403)

    def keys(self, identity, request=''):
        return (f'makeup:beta:{identity}', f'makeup:beta:{identity}:used', f'makeup:beta:{identity}:request:{request}')

    def redeem(self, code):
        self.enabled()
        if not isinstance(code, str) or not 12 <= len(code.strip()) <= 100 or not hmac.compare_digest(hashlib.sha256(code.strip().encode()).hexdigest(), self.digest):
            raise SubscriptionError('测试码无效 / Invalid test code.', 'INVALID_TEST_CODE', 403)
        identity = self.store.digest('beta-code:' + self.digest)
        key, _, _ = self.keys(identity)
        # Never refresh expiry or quota on another redemption, reinstall or device.
        self.store.command('SET', key, json.dumps({'expiresAt': int(self.clock()) + DURATION}), 'NX')
        result = self.public(identity)
        if not result['active']:
            raise SubscriptionError('测试权限已到期 / Test access expired.', 'TEST_ACCESS_EXPIRED', 403)
        payload = {'sub': identity, 'exp': result['expiresAt'], 'purpose': 'mirror-beta'}
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        signature = hmac.new(self.store.secret, ('beta-session:' + body).encode(), hashlib.sha256).hexdigest()
        return {**result, 'sessionToken': 'mt1.' + body + '.' + signature}

    def authenticate(self, authorization):
        self.enabled()
        try:
            token = authorization.removeprefix('Bearer ')
            prefix, body, signature = token.split('.')
            if prefix != 'mt1' or len(token) > 2048: raise ValueError()
            expected = hmac.new(self.store.secret, ('beta-session:' + body).encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected): raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(body))
            identity = self.store.digest('beta-code:' + self.digest)
            if payload['purpose'] != 'mirror-beta' or payload['sub'] != identity or payload['exp'] <= self.clock(): raise ValueError()
            if not self.public(identity)['active']: raise ValueError()
            return identity
        except (ValueError, TypeError, AttributeError, KeyError, UnicodeError) as exc:
            raise SubscriptionError('测试权限已到期或无效 / Test access expired or invalid.', 'INVALID_TEST_SESSION', 401) from exc

    def public(self, identity):
        self.enabled()
        record = self.store.command('GET', self.keys(identity)[0])
        if not record: raise SubscriptionError('Test access unavailable.', 'INVALID_TEST_SESSION', 401)
        expires = json.loads(record)['expiresAt']
        used = int(self.store.command('GET', self.keys(identity)[1]) or 0)
        return {'active': expires > self.clock(), 'productId': None, 'dailyLimit': LIMIT,
                'remaining': max(0, LIMIT-used), 'used': used,
                'resetAt': datetime.fromtimestamp(expires, timezone.utc).isoformat(),
                'expiresAt': expires, 'isTrial': False, 'environment': 'BetaTest'}

    def reserve(self, identity, request):
        self.enabled()
        try: request = str(uuid.UUID(request))
        except (ValueError, TypeError, AttributeError) as exc: raise SubscriptionError('Request ID required.', 'INVALID_REQUEST', 400) from exc
        result = self.store.command('EVAL', RESERVE, 3, *self.keys(identity, request), self.clock())
        if result != 'OK': raise SubscriptionError('测试次数已用完或权限已到期 / Test allowance used or expired.', result, 409 if result == 'DUPLICATE_REQUEST' else 403)
        return request

    def release(self, identity, request):
        _, used, marker = self.keys(identity, request)
        return self.store.command('EVAL', REFUND, 2, used, marker)
