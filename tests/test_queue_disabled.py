import pytest


def test_celery_queue_stays_disabled_even_when_redis_is_configured(monkeypatch):
    from services import queue as queue_module

    monkeypatch.setattr(queue_module.settings, "REDIS_URL", "redis://localhost:6379/0", raising=False)
    service = queue_module.QueueService()
    service.celery_app.send_task = lambda *_args, **_kwargs: pytest.fail("must not publish")

    assert service.enabled is False
    with pytest.raises(RuntimeError, match="not production-ready"):
        service.send_task("tasks.process_signal", args=[1, "BUY EURUSD"])
