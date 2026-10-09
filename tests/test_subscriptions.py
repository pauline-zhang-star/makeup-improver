import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace as NS

import fakeredis
import pytest
from appstoreserverlibrary.models.JWSTransactionDecodedPayload import JWSTransactionDecodedPayload
from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.models.Type import Type
from appstoreserverlibrary.models.InAppOwnershipType import InAppOwnershipType

from makeup_refine.public_guard import SignedVisitors
from makeup_refine.subscriptions import (AppleSubscriptions, SubscriptionService, SubscriptionError,
                                        BUNDLE_ID, GROUP_ID, SAVE_SCRIPT)


class Store(SignedVisitors):
    def __init__(self):
        super().__init__('local-test-secret')
        self.redis = fakeredis.FakeRedis(decode_responses=True)

    def command(self, *parts):
        return self.redis.execute_command(*parts)


class Apple:
    def __init__(self, tx):
        self.tx = tx
        self.status = 1
        self.calls = 0
        self.fail = False
        self.on_status = None

    def decode(self, signed, notification=False):
        if signed == 'forged':
            raise SubscriptionError('Invalid', 'INVALID_TRANSACTION', 401)
        if notification:
            return 'Sandbox', NS(notificationUUID='event-1', data=NS(signedTransactionInfo='current'),
                                 notificationType='REFUND', signedDate=self.tx.signedDate)
        return self.tx.environment.value, self.tx

    def current(self, environment, original):
        self.calls += 1
        if self.fail:
            raise SubscriptionError('Apple unavailable')
        if self.on_status:
            self.on_status()
        return NS(data=[NS(subscriptionGroupIdentifier=GROUP_ID,
                           lastTransactions=[NS(signedTransactionInfo='current', status=self.status)])])


@pytest.fixture
def setup():
    clock = [1791540000.0]
    tx = JWSTransactionDecodedPayload(
        originalTransactionId='123', transactionId='456', appTransactionId='stable-user',
        bundleId=BUNDLE_ID, productId=BUNDLE_ID + '.plus.monthly',
        subscriptionGroupIdentifier=GROUP_ID, expiresDate=int((clock[0] + 86400) * 1000),
        signedDate=int(clock[0] * 1000), type=Type.AUTO_RENEWABLE_SUBSCRIPTION,
        inAppOwnershipType=InAppOwnershipType.PURCHASED, environment=Environment.SANDBOX)
    store, apple = Store(), Apple(tx)
    service = SubscriptionService(store, apple, clock=lambda: clock[0])
    return service, apple, clock


def owner(service):
    result = service.synchronize('current')
    return service.authenticate('Bearer ' + result['sessionToken'])


def test_renewal_restore_upgrade_and_new_chain_do_not_reset_daily_usage(setup):
    service, apple, _ = setup
    identity = owner(service)
    service.reserve(identity, str(uuid.uuid4()))
    apple.tx.transactionId = 'renewal'
    apple.tx.productId = BUNDLE_ID + '.premium.weekly'
    apple.tx.originalTransactionId = 'new-chain'
    identity2 = owner(service)
    assert identity == identity2
    assert service.public(identity)['remaining'] == 2
    assert service.public(identity)['used'] == 1
    assert 'current' not in service.store.command('GET', service.key(identity))


def test_concurrent_requests_cannot_exceed_daily_allowance(setup):
    service, _, _ = setup
    identity = owner(service)

    def attempt(_):
        try:
            service.reserve(identity, str(uuid.uuid4()))
            return 'OK'
        except SubscriptionError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(12)))
    assert results.count('OK') == 2
    assert results.count('SUBSCRIPTION_DAILY_LIMIT') == 10
    assert service.public(identity)['used'] == 2


def test_duplicate_and_refunded_request_cannot_generate_again(setup):
    service, _, _ = setup
    identity = owner(service)
    request = str(uuid.uuid4())
    service.reserve(identity, request)
    with pytest.raises(SubscriptionError, match='allowance') as caught:
        service.reserve(identity, request)
    assert caught.value.code == 'DUPLICATE_REQUEST'
    assert service.release(identity, request) == 1
    assert service.release(identity, request) == 0
    assert service.public(identity)['remaining'] == 2
    with pytest.raises(SubscriptionError) as caught:
        service.reserve(identity, request)
    assert caught.value.code == 'DUPLICATE_REQUEST'


def test_refund_crossing_midnight_releases_original_day_only(setup):
    service, _, clock = setup
    identity = owner(service)
    request = str(uuid.uuid4())
    service.reserve(identity, request)
    clock[0] += 86400
    service.refresh(identity)
    new = str(uuid.uuid4())
    # Extend current transaction for the next day.
    service.apple.tx.expiresDate += 86400000
    service.refresh(identity)
    service.reserve(identity, new)
    assert service.release(identity, request) == 1
    assert service.public(identity)['used'] == 1


@pytest.mark.parametrize('status', [2, 3, 4, 5])
def test_old_signed_purchase_does_not_grant_expired_retry_grace_or_revoked_access(setup, status):
    service, apple, _ = setup
    apple.status = status
    identity = owner(service)
    assert service.public(identity)['active'] is False
    with pytest.raises(SubscriptionError) as caught:
        service.reserve(identity, str(uuid.uuid4()))
    assert caught.value.code == 'SUBSCRIPTION_REQUIRED'


@pytest.mark.parametrize('field,value', [('bundleId', 'another.app'), ('productId', 'unknown'),
    ('subscriptionGroupIdentifier', 'other'), ('inAppOwnershipType', InAppOwnershipType.FAMILY_SHARED)])
def test_rejects_wrong_app_product_group_and_shared_purchase(setup, field, value):
    service, apple, _ = setup
    setattr(apple.tx, field, value)
    with pytest.raises(SubscriptionError) as caught:
        owner(service)
    assert caught.value.code == 'INVALID_TRANSACTION'


def test_stale_status_fails_closed_when_apple_is_unavailable(setup):
    service, apple, clock = setup
    identity = owner(service)
    clock[0] += 61
    apple.fail = True
    with pytest.raises(SubscriptionError):
        service.reserve(identity, str(uuid.uuid4()))
    assert service.store.command('GET', service.quota_keys(identity, 'unused', '2026-10-09')[1]) is None


def test_refund_notifications_are_idempotent_and_reconcile_before_generation(setup):
    service, apple, clock = setup
    identity = owner(service)
    clock[0] += 1
    apple.tx.signedDate = int(clock[0] * 1000)
    apple.status = 5
    assert service.notification('refund') == {'ok': True}
    service.notification('refund')
    assert service.public(identity)['active'] is False
    with pytest.raises(SubscriptionError):
        service.reserve(identity, str(uuid.uuid4()))


def test_inflight_status_response_cannot_overwrite_newer_refund(setup):
    service, apple, clock = setup
    identity = owner(service)
    clock[0] += 61
    def refund():
        record = service.load(identity)
        record.update(active=False, dailyLimit=0, checkedAt=0, revision=(clock[0] + 1) * 1000)
        service.store.command('EVAL', SAVE_SCRIPT, 1, service.key(identity), json.dumps(record), record['revision'])
    apple.on_status = refund
    assert service.refresh(identity)['active'] is False


def test_sessions_are_signed_purpose_scoped_and_expire(setup):
    service, _, clock = setup
    identity = owner(service)
    token = service.session(identity)
    with pytest.raises(SubscriptionError):
        service.authenticate('Bearer ' + token[:-1] + ('a' if token[-1] != 'a' else 'b'))
    clock[0] += 3601
    with pytest.raises(SubscriptionError) as caught:
        service.authenticate('Bearer ' + token)
    assert caught.value.code == 'INVALID_SESSION'


def test_paid_global_limit_and_sandbox_production_are_separate(setup):
    service, apple, _ = setup
    service.global_limit = 1
    identity = owner(service)
    service.reserve(identity, str(uuid.uuid4()))
    with pytest.raises(SubscriptionError) as caught:
        service.reserve(identity, str(uuid.uuid4()))
    assert caught.value.code == 'SERVICE_DAILY_LIMIT'
    apple.tx.environment = Environment.PRODUCTION
    live = owner(service)
    assert identity != live
    service.reserve(live, str(uuid.uuid4()))


def test_official_verifier_rejects_forged_jws_and_local_storekit_data():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    root = Path('certificates/apple/AppleRootCA-G3.cer').read_bytes()
    apple = AppleSubscriptions([root], key, 'test', 'test', allow_sandbox=True)
    for fake in ['forged', 'eyJhbGciOiJub25lIn0.eyJlbnZpcm9ubWVudCI6Ilhjb2RlIn0.', None]:
        with pytest.raises(SubscriptionError):
            apple.decode(fake)
