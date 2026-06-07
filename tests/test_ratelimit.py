"""Unit tests for the control-plane rate limiter (no HTTP layer, no shared state)."""

from src.api.ratelimit import RateLimiter


def test_blocks_after_max_within_window():
    rl = RateLimiter(max_requests=3, window_seconds=60)
    assert [rl.allow("ip1") for _ in range(3)] == [True, True, True]
    assert rl.allow("ip1") is False          # 4th request blocked
    assert rl.allow("ip1") is False          # stays blocked


def test_keys_are_isolated():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("ip1") is True
    assert rl.allow("ip1") is False
    assert rl.allow("ip2") is True           # a different client is unaffected


def test_reset_clears_state():
    rl = RateLimiter(max_requests=1, window_seconds=60)
    assert rl.allow("k") is True
    assert rl.allow("k") is False
    rl.reset()
    assert rl.allow("k") is True             # window cleared
