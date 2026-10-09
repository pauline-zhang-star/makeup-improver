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
