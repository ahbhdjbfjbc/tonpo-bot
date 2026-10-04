import asyncio

from services import cache as cache_module
from services import queue as queue_module
from services.cache import CacheService
from services.queue import AsyncTaskManager, QueueService
from services.subscription import SubscriptionService


def test_cache_without_redis_url_stays_disabled(monkeypatch):
    monkeypatch.setattr(cache_module.settings, "REDIS_URL", None, raising=False)

    def unexpected_connect(*args, **kwargs):
        raise AssertionError("redis.from_url must not receive a missing URL")

    monkeypatch.setattr(cache_module.redis, "from_url", unexpected_connect)
    cache = CacheService()

    assert cache.redis_client is None
    assert cache.get("missing", "fallback") == "fallback"
    assert cache.set("key", "value") is False


def test_queue_without_redis_url_is_offline_and_explicit(monkeypatch):
    monkeypatch.setattr(queue_module.settings, "REDIS_URL", None, raising=False)
    queue = QueueService()

    assert queue.enabled is False
    try:
        queue.send_task("tasks.example")
    except RuntimeError as exc:
        assert "REDIS_URL" in str(exc)
    else:
        raise AssertionError("sending a task without Redis must fail clearly")


def test_async_task_manager_constructs_without_event_loop_and_binds_later():
    manager = AsyncTaskManager()
    assert manager.loop is None

    async def run():
        async def work():
            return "done"

        task_id = manager.create_task(work(), "task-1")
        assert await manager.wait_for_task(task_id) == "done"
        await asyncio.sleep(0)
        assert manager.get_task_status(task_id) is None

    asyncio.run(run())
    assert manager.loop is not None


def test_expired_subscription_notification_works_without_implicit_loop():
    service = SubscriptionService.__new__(SubscriptionService)
    user = type("ExpiredUser", (), {"subscription_tier": "basic", "telegram_id": 17})()
    service.get_expired = lambda: [user]
    service.downgrade_user = lambda user_id, reason: None

    class Notification:
        templates = {"subscription_expired": "Plan {plan} expired"}

        def __init__(self):
            self.sent = []

        async def send_telegram(self, user_id, message):
            self.sent.append((user_id, message))

    notification = Notification()
    assert service.process_expired(notification) == 1
    assert notification.sent == [(17, "Plan basic expired")]
