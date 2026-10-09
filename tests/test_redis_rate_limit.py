import threading

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from bot.middleware import RateLimitMiddleware
from services.cache import (
    CacheService,
    RateLimitUnavailable,
    _RATE_LIMIT_SCRIPT,
)


class FakeAtomicCache:
    def __init__(self):
        self.now = 0.0
        self.state = {}
        self.calls = []
        self.lock = threading.Lock()

    def check_rate_limit(self, key, limit, period):
        with self.lock:
            self.calls.append((key, limit, period))
            count, expires_at = self.state.get(key, (0, self.now))
            if expires_at <= self.now:
                count, expires_at = 0, self.now + period
            if count >= limit:
                return False, max(0, int(expires_at - self.now))
            self.state[key] = (count + 1, expires_at)
            return True, max(0, int(expires_at - self.now))


def _limiter(monkeypatch, cache):
    import services.subscription as subscription

    class NoPlan:
        def __init__(self, _session):
            pass

        def get_user_plan(self, _user_id):
            return None

    monkeypatch.setattr(subscription, "SubscriptionService", NoPlan)
    return RateLimitMiddleware(cache)


def test_rate_limit_window_and_identity_isolation(monkeypatch):
    cache = FakeAtomicCache()
    limiter = _limiter(monkeypatch, cache)

    assert [limiter.check_rate_limit(10, "trade")[0] for _ in range(5)] == [True] * 5
    assert limiter.check_rate_limit(10, "trade")[0] is False
    assert limiter.check_rate_limit(11, "trade")[0] is True
    assert limiter.check_rate_limit(10, "balance")[0] is True

    cache.now = 60.0
    assert limiter.check_rate_limit(10, "trade")[0] is True
    assert cache.calls[0][0] == "ratelimit:bot:10:trade"


def test_rate_limit_uses_one_atomic_cache_operation(monkeypatch):
    cache = FakeAtomicCache()
    limiter = _limiter(monkeypatch, cache)

    assert limiter.check_rate_limit(42, "trade")[0] is True
    assert cache.calls == [("ratelimit:bot:42:trade", 5, 60)]


def test_rate_limit_fails_closed_when_redis_is_unavailable(monkeypatch):
    class UnavailableCache:
        def check_rate_limit(self, *_args):
            raise RateLimitUnavailable("test failure")

    limiter = _limiter(monkeypatch, UnavailableCache())
    allowed, retry_after = limiter.check_rate_limit(42, "trade")

    assert allowed is False
    assert retry_after == 60


def test_cache_rate_limit_rejects_missing_redis_without_fallback():
    cache = CacheService.__new__(CacheService)
    cache._ensure_connection = lambda: False

    with pytest.raises(RateLimitUnavailable):
        cache.check_rate_limit("ratelimit:bot:1:trade", 5, 60)


def test_cache_rate_limit_rejects_command_errors_and_malformed_results():
    cache = CacheService.__new__(CacheService)

    class BrokenRedis:
        def eval(self, *_args):
            raise RedisConnectionError("test failure")

    cache.redis_client = BrokenRedis()
    cache._ensure_connection = lambda: True
    with pytest.raises(RateLimitUnavailable):
        cache.check_rate_limit("ratelimit:bot:1:trade", 5, 60)

    class MalformedRedis:
        def eval(self, *_args):
            return [2, 60]

    cache.redis_client = MalformedRedis()
    with pytest.raises(RateLimitUnavailable):
        cache.check_rate_limit("ratelimit:bot:1:trade", 5, 60)


def test_rate_limit_script_is_server_side_atomic_and_ttl_bounded():
    assert "redis.call('GET'" in _RATE_LIMIT_SCRIPT
    assert "redis.call('INCR'" in _RATE_LIMIT_SCRIPT
    assert "redis.call('EXPIRE'" in _RATE_LIMIT_SCRIPT
    assert "ARGV[1]" in _RATE_LIMIT_SCRIPT
    assert "ARGV[2]" in _RATE_LIMIT_SCRIPT
