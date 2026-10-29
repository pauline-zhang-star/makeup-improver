import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest
from makeup_refine.test_access import TestAccess, DURATION
from makeup_refine.subscriptions import SubscriptionError
from test_subscriptions import Store

CODE = 'private-test-code-1234567890'

def service():
    now = [1000000.0]
    store = Store()
    s = TestAccess(store, hashlib.sha256(CODE.encode()).hexdigest(), lambda: now[0])
    return s, now

def test_shared_total_and_concurrency_are_atomic():
    s, _ = service()
    a = s.redeem(CODE)
    identity = s.authenticate('Bearer ' + a['sessionToken'])
    def reserve(_):
        try: s.reserve(identity, str(uuid.uuid4())); return True
        except SubscriptionError as e: assert e.code == 'TEST_LIMIT_REACHED'; return False
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(reserve, range(30))) == 10
    assert s.redeem(CODE)['remaining'] == 0

def test_redemption_does_not_extend_expiry_and_expiry_is_enforced():
    s, now = service()
    access = s.redeem(CODE)
    identity = s.authenticate('Bearer ' + access['sessionToken'])
    now[0] += 86400
    assert s.redeem(CODE)['expiresAt'] == access['expiresAt']
    now[0] += DURATION
    for call in [lambda: s.redeem(CODE), lambda: s.authenticate('Bearer '+access['sessionToken']), lambda: s.reserve(identity, str(uuid.uuid4()))]:
        with pytest.raises(SubscriptionError): call()

def test_invalid_codes_tamper_disable_and_code_rotation_fail_closed():
    s, _ = service()
    with pytest.raises(SubscriptionError): s.redeem('wrong-but-long-code')
    token = s.redeem(CODE)['sessionToken']
    with pytest.raises(SubscriptionError): s.authenticate('Bearer '+token+'bad')
    s.digest = ''
    with pytest.raises(SubscriptionError): s.authenticate('Bearer '+token)
    s.digest = hashlib.sha256(b'a-new-long-test-code').hexdigest()
    with pytest.raises(SubscriptionError): s.authenticate('Bearer '+token)

def test_request_replay_and_refund_never_restore_twice():
    s, _ = service()
    identity = s.authenticate('Bearer '+s.redeem(CODE)['sessionToken'])
    request = str(uuid.uuid4())
    s.reserve(identity, request)
    assert s.public(identity)['remaining'] == 9
    with pytest.raises(SubscriptionError): s.reserve(identity, request)
    assert s.release(identity, request) == 1
    assert s.release(identity, request) == 0
    assert s.public(identity)['remaining'] == 10
    with pytest.raises(SubscriptionError): s.reserve(identity, request)


def test_separate_invites_keep_independent_quotas_and_revocation():
    s, _ = service()
    other = 'another-private-invitation-12345'
    first_digest = s.digest
    second_digest = hashlib.sha256(other.encode()).hexdigest()
    s.digest += ',' + second_digest
    first = s.redeem(CODE)
    second = s.redeem(other)
    a = s.authenticate('Bearer ' + first['sessionToken'])
    b = s.authenticate('Bearer ' + second['sessionToken'])
    assert a != b
    s.reserve(a, str(uuid.uuid4()))
    assert s.public(a)['remaining'] == 9
    assert s.public(b)['remaining'] == 10
    s.digest = second_digest
    with pytest.raises(SubscriptionError):
        s.authenticate('Bearer ' + first['sessionToken'])
    assert s.authenticate('Bearer ' + second['sessionToken']) == b
    s.digest = first_digest + ',' + second_digest
    assert s.redeem(CODE)['remaining'] == 9


def test_malformed_invitation_configuration_fails_closed():
    s, _ = service()
    for value in [s.digest + ',', s.digest + ',invalid', ','.join([s.digest] * 101)]:
        s.digest = value
        with pytest.raises(SubscriptionError):
            s.redeem(CODE)


def test_custom_signed_codes_independent_limits_expiry_and_tampering():
    from makeup_refine.beta_codes import issue
    s, now = service()
    s.issuer_secret = 'a' * 64
    s.digest = ''
    code = issue(s.issuer_secret, 3, 2)
    other = issue(s.issuer_secret, 6, 7)
    access = s.redeem(code)
    assert access['dailyLimit'] == 3
    identity = s.authenticate('Bearer ' + access['sessionToken'])
    for _ in range(3):
        s.reserve(identity, str(uuid.uuid4()))
    with pytest.raises(SubscriptionError): s.reserve(identity, str(uuid.uuid4()))
    assert s.redeem(code)['remaining'] == 0
    assert s.redeem(other)['remaining'] == 6
    with pytest.raises(SubscriptionError): s.redeem(code.replace('.3.2.', '.9.2.'))
    now[0] += 2 * 86400
    with pytest.raises(SubscriptionError): s.redeem(code)
    with pytest.raises(SubscriptionError): s.authenticate('Bearer ' + access['sessionToken'])
    assert s.redeem(other)['active']


def test_signed_code_rotation_revokes_existing_sessions():
    from makeup_refine.beta_codes import issue
    s, _ = service()
    s.issuer_secret = 'b' * 64
    token = s.redeem(issue(s.issuer_secret, 1, 30))['sessionToken']
    s.issuer_secret = 'c' * 64
    with pytest.raises(SubscriptionError): s.authenticate('Bearer ' + token)


def test_custom_quota_reservations_are_atomic_and_refund_once():
    from makeup_refine.beta_codes import issue
    s, _ = service()
    s.issuer_secret = 'a' * 64
    identity = s.authenticate('Bearer ' + s.redeem(issue(s.issuer_secret, 2, 30))['sessionToken'])
    def reserve(_):
        try: s.reserve(identity, str(uuid.uuid4())); return True
        except SubscriptionError as exc: assert exc.code == 'TEST_LIMIT_REACHED'; return False
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert sum(pool.map(reserve, range(20))) == 2


def test_short_codes_preserve_original_quota_expiry_and_session():
    from makeup_refine.beta_codes import issue
    s, now = service()
    s.issuer_secret = 'a' * 64
    long_code = issue(s.issuer_secret, 3, 7)
    first = s.redeem(long_code)
    identity = s.authenticate('Bearer ' + first['sessionToken'])
    s.reserve(identity, str(uuid.uuid4()))
    now[0] += 3600
    short = s.shorten(long_code)['code']
    assert len(short) == 14
    access = s.redeem(short.lower().replace('-', ''))
    assert access['remaining'] == 2 and access['expiresAt'] == first['expiresAt']
    assert s.authenticate('Bearer ' + access['sessionToken']) == identity
    assert s.shorten(long_code)['code'] == short
    with pytest.raises(SubscriptionError): s.shorten(long_code[:-1] + 'x')
    s.issuer_secret = 'b' * 64
    with pytest.raises(SubscriptionError): s.redeem(short)


def test_short_issuance_is_atomic_and_distinct_invites_stay_separate():
    from makeup_refine.beta_codes import issue
    s, _ = service()
    s.issuer_secret = 'a' * 64
    long_code = issue(s.issuer_secret, 2, 30)
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: s.shorten(long_code)['code'], range(25)))
    assert len(set(results)) == 1
    other = s.shorten(issue(s.issuer_secret, 5, 7))['code']
    assert other != results[0]
    assert s.redeem(results[0])['dailyLimit'] == 2
    assert s.redeem(other)['dailyLimit'] == 5
