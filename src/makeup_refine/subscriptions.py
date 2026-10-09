"""Apple-verified, account-free subscriptions and atomic Redis daily allowances.

No photo, purchase JWS or private Apple key is persisted in the entitlement ledger.
Xcode's local StoreKit signatures are deliberately NOT trusted by this server.
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
from pathlib import Path

from .public_guard import next_utc_day, utc_day

BUNDLE_ID = 'com.makeuptutor.app'
APP_ID = 6821052986
GROUP_ID = '22459343'
PRODUCTS = {f'{BUNDLE_ID}.{tier}.{period}': allowance
            for tier, allowance in [('basic', 1), ('plus', 2), ('premium', 3)]
            for period in ('monthly', 'weekly')}
SESSION_TTL = 3600
FRESH_SECONDS = 60


class SubscriptionError(Exception):
    def __init__(self, message, code='SUBSCRIPTION_UNAVAILABLE', status=503):
        super().__init__(message)
        self.code, self.status = code, status


# A status lookup begun before a refund notification cannot overwrite that notification.
SAVE_SCRIPT = '''
local old = redis.call('GET', KEYS[1])
if old then
  local previous = cjson.decode(old)
  if tonumber(previous.revision) > tonumber(ARGV[2]) then return old end
end
redis.call('SET', KEYS[1], ARGV[1])
return ARGV[1]
'''
RESERVE_SCRIPT = '''
local saved = redis.call('GET', KEYS[1])
if not saved then return 'SUBSCRIPTION_REQUIRED' end
local e = cjson.decode(saved)
if not e.active or tonumber(e.expiresAt) <= tonumber(ARGV[1]) then
  return 'SUBSCRIPTION_REQUIRED'
end
if tonumber(e.checkedAt) < tonumber(ARGV[1]) - 60 then return 'STATUS_STALE' end
if redis.call('EXISTS', KEYS[4]) == 1 then return 'DUPLICATE_REQUEST' end
local used = tonumber(redis.call('GET', KEYS[2]) or '0')
if used >= tonumber(e.dailyLimit) then return 'SUBSCRIPTION_DAILY_LIMIT' end
local global = tonumber(redis.call('GET', KEYS[3]) or '0')
if global >= tonumber(ARGV[2]) then return 'SERVICE_DAILY_LIMIT' end
redis.call('INCR', KEYS[2]); redis.call('EXPIRE', KEYS[2], 172800)
redis.call('INCR', KEYS[3]); redis.call('EXPIRE', KEYS[3], 172800)
redis.call('SET', KEYS[4], ARGV[3], 'EX', 172800)
return 'OK'
'''
RELEASE_SCRIPT = '''
if redis.call('GET', KEYS[3]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[3], 'refunded', 'EX', 172800)
if tonumber(redis.call('GET', KEYS[1]) or '0') > 0 then redis.call('DECR', KEYS[1]) end
if tonumber(redis.call('GET', KEYS[2]) or '0') > 0 then redis.call('DECR', KEYS[2]) end
return 1
'''


class AppleSubscriptions:
    """Small adapter around Apple's official library; no unverified JWT decoding."""
    def __init__(self, roots, private_key, key_id, issuer_id, allow_sandbox=False):
        from appstoreserverlibrary.api_client import AppStoreServerAPIClient
        from appstoreserverlibrary.models.Environment import Environment
        from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
        environments = [Environment.PRODUCTION]
        if allow_sandbox:
            environments.append(Environment.SANDBOX)
        self.verifiers = {e.value: SignedDataVerifier(roots, True, e, BUNDLE_ID, APP_ID)
                          for e in environments}
        self.clients = {e.value: AppStoreServerAPIClient(private_key, key_id, issuer_id,
                                                        BUNDLE_ID, e) for e in environments}

    def decode(self, signed, notification=False):
        if not isinstance(signed, str) or not 0 < len(signed) <= 100_000:
            raise SubscriptionError('Invalid Apple transaction.', 'INVALID_TRANSACTION', 400)
        for environment, verifier in self.verifiers.items():
            try:
                method = (verifier.verify_and_decode_notification if notification
                          else verifier.verify_and_decode_signed_transaction)
                return environment, method(signed)
            except Exception:
                continue
        raise SubscriptionError('Apple transaction verification failed.', 'INVALID_TRANSACTION', 401)

    def current(self, environment, original_id):
        try:
            return self.clients[environment].get_all_subscription_statuses(original_id)
        except Exception as exc:
            raise SubscriptionError('Could not check your subscription. Try again shortly.') from exc


def environment_value(value):
    return getattr(value, 'value', value)


def validate_transaction(tx, environment):
    if (tx.bundleId != BUNDLE_ID or tx.productId not in PRODUCTS
            or tx.subscriptionGroupIdentifier != GROUP_ID
            or environment_value(tx.environment) != environment
            or not tx.originalTransactionId or not tx.transactionId
            or environment_value(tx.type) != 'Auto-Renewable Subscription'
            or environment_value(tx.inAppOwnershipType) != 'PURCHASED'):
        raise SubscriptionError('This purchase does not belong to Mirror.', 'INVALID_TRANSACTION', 401)


class SubscriptionService:
    def __init__(self, store, apple, clock=time.time, global_limit=1000):
        self.store, self.apple, self.clock = store, apple, clock
        self.global_limit = global_limit

    @classmethod
    def from_environment(cls, store):
        if os.environ.get('MAKEUP_SUBSCRIPTIONS_ENABLED') != '1':
            raise SubscriptionError('Subscriptions are not configured yet.')
        names = ['APPLE_IAP_PRIVATE_KEY', 'APPLE_IAP_KEY_ID', 'APPLE_IAP_ISSUER_ID']
        if not all(os.environ.get(name) for name in names):
            raise SubscriptionError('Subscriptions are not configured yet.')
        root = Path(__file__).resolve().parents[2] / 'certificates' / 'apple' / 'AppleRootCA-G3.cer'
        roots = [root.read_bytes()]
        apple = AppleSubscriptions(roots, os.environ[names[0]].replace('\\n', '\n').encode(),
                                   os.environ[names[1]], os.environ[names[2]],
                                   os.environ.get('APPLE_ALLOW_SANDBOX') == '1')
        limit = int(os.environ.get('MAKEUP_SUBSCRIPTION_GLOBAL_DAILY_LIMIT', '1000'))
        if limit < 1:
            raise SubscriptionError('Invalid subscription service limit.')
        return cls(store, apple, global_limit=limit)

    def identity(self, tx, environment):
        # appTransactionId is Apple-signed and stable per Apple Account/app, even
        # across different original subscription chains. Older JWS falls back
        # to the chain ID, which remains stable through upgrades and renewals.
        source = 'app:' + tx.appTransactionId if tx.appTransactionId else 'chain:' + tx.originalTransactionId
        return self.store.digest('subscription:' + environment + ':' + source)

    def key(self, identity):
        return 'makeup:subscription:' + identity

    def load(self, identity):
        saved = self.store.command('GET', self.key(identity))
        if not saved:
            raise SubscriptionError('Restore your subscription to continue.', 'SUBSCRIPTION_REQUIRED', 403)
        return json.loads(saved)

    def session(self, identity):
        payload = {'sub': identity, 'exp': int(self.clock()) + SESSION_TTL, 'purpose': 'mirror-subscription'}
        body = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode()
        signature = hmac.new(self.store.secret, ('subscription-session:' + body).encode(), hashlib.sha256).hexdigest()
        return body + '.' + signature

    def authenticate(self, authorization):
        try:
            if not isinstance(authorization, str) or not authorization.startswith('Bearer '):
                raise ValueError()
            token = authorization[7:]
            if len(token) > 2048:
                raise ValueError()
            body, signature = token.rsplit('.', 1)
            expected = hmac.new(self.store.secret, ('subscription-session:' + body).encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(body))
            if (payload['exp'] <= self.clock() or payload['purpose'] != 'mirror-subscription'
                    or not re.fullmatch(r'[a-f0-9]{64}', payload['sub'])):
                raise ValueError()
            return payload['sub']
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise SubscriptionError('Refresh your subscription to continue.', 'INVALID_SESSION', 401) from exc

    def synchronize(self, signed):
        environment, tx = self.apple.decode(signed)
        validate_transaction(tx, environment)
        identity = self.identity(tx, environment)
        record = self.refresh(identity, tx, environment)
        return {'sessionToken': self.session(identity), **self.public(identity, record)}

    def refresh(self, identity, tx=None, environment=None):
        started = self.clock()
        previous = None
        if tx is None:
            previous = self.load(identity)
            environment, original = previous['environment'], previous['originalId']
        else:
            original = tx.originalTransactionId
        response = self.apple.current(environment, original)
        candidates = []
        for group in response.data or []:
            if group.subscriptionGroupIdentifier != GROUP_ID:
                continue
            for item in group.lastTransactions or []:
                env, current = self.apple.decode(item.signedTransactionInfo)
                validate_transaction(current, env)
                if env != environment or self.identity(current, env) != identity:
                    raise SubscriptionError('Subscription owner did not match.', 'INVALID_TRANSACTION', 401)
                active = (environment_value(item.status) == 1 and not current.revocationDate
                          and not current.isUpgraded and (current.expiresDate or 0) > self.clock() * 1000)
                # Grace access is disabled until a product policy is selected.
                candidates.append((active, current.expiresDate or 0, current, item.status))
        if candidates:
            active, _, current, status = max(candidates, key=lambda c: (c[0], c[1]))
            original = current.originalTransactionId
            product = current.productId
            expires = (current.expiresDate or 0) / 1000
            trial = environment_value(current.offerDiscountType) == 'FREE_TRIAL'
        else:
            active, product, expires, trial = False, None, 0, False
        record = {'environment': environment, 'originalId': original,
                  'active': bool(active), 'productId': product,
                  'dailyLimit': PRODUCTS.get(product, 0) if active else 0,
                  'expiresAt': expires, 'isTrial': bool(trial),
                  'checkedAt': started, 'revision': started * 1000}
        result = self.store.command('EVAL', SAVE_SCRIPT, 1, self.key(identity),
                                    json.dumps(record), record['revision'])
        return json.loads(result)

    def current(self, identity):
        record = self.load(identity)
        if record['checkedAt'] < self.clock() - FRESH_SECONDS:
            record = self.refresh(identity)
        return record

    def quota_keys(self, identity, request_id, day):
        record = self.load(identity)
        return (self.key(identity), f'makeup:paid:q:{day}:{identity}',
                f"makeup:paid:q:{day}:all:{record['environment']}",
                f'makeup:paid:request:{identity}:{request_id}')

    def public(self, identity, record=None):
        record = record or self.current(identity)
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        used = int(self.store.command('GET', f'makeup:paid:q:{utc_day(now)}:{identity}') or 0)
        active = record['active'] and record['expiresAt'] > self.clock()
        limit = record['dailyLimit'] if active else 0
        return {'active': bool(active), 'productId': record['productId'], 'dailyLimit': limit,
                'remaining': max(0, limit - used), 'used': used, 'resetAt': next_utc_day(now),
                'expiresAt': record['expiresAt'], 'isTrial': record['isTrial'],
                'environment': record['environment']}

    def reserve(self, identity, request_id):
        try:
            request_id = str(uuid.UUID(request_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise SubscriptionError('A request ID is required.', 'INVALID_REQUEST', 400) from exc
        self.current(identity)
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        day = utc_day(now)
        result = self.store.command('EVAL', RESERVE_SCRIPT, 4,
                                    *self.quota_keys(identity, request_id, day),
                                    self.clock(), self.global_limit, day)
        if result != 'OK':
            status = 403 if result == 'SUBSCRIPTION_REQUIRED' else 409 if result == 'DUPLICATE_REQUEST' else 429
            raise SubscriptionError('Your subscription allowance is unavailable or used for today.', result, status)
        return request_id

    def release(self, identity, request_id):
        reservation = f'makeup:paid:request:{identity}:{request_id}'
        day = self.store.command('GET', reservation)
        if not day or day == 'refunded':
            return 0
        _, personal, global_key, _ = self.quota_keys(identity, request_id, day)
        # Keep a consumed request marker after refunding. Reusing a request ID
        # cannot trigger a second chargeable attempt with an ambiguous result.
        result = self.store.command('EVAL', RELEASE_SCRIPT, 3, personal, global_key, reservation, day)
        return result

    def notification(self, signed):
        environment, payload = self.apple.decode(signed, notification=True)
        if not payload.notificationUUID:
            raise SubscriptionError('Invalid notification.', 'INVALID_NOTIFICATION', 400)
        data = payload.data
        if data and data.signedTransactionInfo:
            env, tx = self.apple.decode(data.signedTransactionInfo)
            validate_transaction(tx, env)
            if env != environment:
                raise SubscriptionError('Invalid notification environment.', 'INVALID_NOTIFICATION', 400)
            identity = self.identity(tx, env)
            # Invalidate immediately. A later access reconciles against Apple's
            # status API, including refunds, revocations and renewals.
            try:
                record = self.load(identity)
            except SubscriptionError as exc:
                if exc.code != 'SUBSCRIPTION_REQUIRED':
                    raise
                record = None
            if record:
                record['checkedAt'] = 0
                record['revision'] = float(payload.signedDate or self.clock() * 1000)
                if environment_value(payload.notificationType) in {'REFUND', 'REVOKE', 'EXPIRED'}:
                    record.update(active=False, dailyLimit=0)
                self.store.command('EVAL', SAVE_SCRIPT, 1, self.key(identity),
                                   json.dumps(record), record['revision'])
        return {'ok': True}
