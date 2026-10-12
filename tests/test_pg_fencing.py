"""Real two-client PostgreSQL leader fencing and lease expiry tests."""
import os
import time
import uuid
import pytest

pytestmark=pytest.mark.skipif(not os.getenv("AGENTBRIDGE_TEST_PG"),
                              reason="needs disposable PostgreSQL test instance")


def test_fencing_epochs_reject_stale_leaders_across_connections():
    from src.governance.pg_fencing import PgFencing,FenceDenied
    service=PgFencing(os.environ["AGENTBRIDGE_TEST_PG"])
    service.initialize()
    scope="fence-"+uuid.uuid4().hex
    first=service.acquire(scope,"worker-a",ttl_seconds=.6)
    assert first==1
    assert service.check(scope,"worker-a",first)
    with pytest.raises(FenceDenied,match="already held"):
        service.acquire(scope,"worker-b",ttl_seconds=1)
    assert service.renew(scope,"worker-a",first,ttl_seconds=.6)==first
    time.sleep(.85)
    assert not service.check(scope,"worker-a",first)
    second=PgFencing(os.environ["AGENTBRIDGE_TEST_PG"]).acquire(
        scope,"worker-b",ttl_seconds=10)
    assert second>first
    assert service.check(scope,"worker-b",second)
    assert not service.check(scope,"worker-a",first)
    with pytest.raises(FenceDenied,match="stale"):
        service.renew(scope,"worker-a",first)
    with pytest.raises(FenceDenied,match="already held"):
        service.acquire(scope,"worker-a",ttl_seconds=10)


def test_fencing_rejects_bad_epoch_and_ttl():
    from src.governance.pg_fencing import PgFencing,FenceDenied
    service=PgFencing(os.environ["AGENTBRIDGE_TEST_PG"])
    service.initialize()
    scope="fence-"+uuid.uuid4().hex
    for val in (float("nan"),float("inf"),0,-2,3601):
        with pytest.raises(FenceDenied):
            service.acquire(scope,"worker",ttl_seconds=val)
    assert not service.check(scope,"worker",True)
