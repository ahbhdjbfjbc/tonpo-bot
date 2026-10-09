"""PHASE B request-session lifecycle guard."""

from types import SimpleNamespace


def test_web_runtime_rebuilds_executor_for_each_request_session(monkeypatch):
    import web.runtime as runtime

    first_db = object()
    second_db = object()
    provider = SimpleNamespace()
    monkeypatch.setattr(runtime, "_pipeline", None)
    monkeypatch.setattr(runtime, "_executor", None)
    monkeypatch.setattr(runtime, "_execution_provider", provider)

    first_pipeline = runtime.get_signal_pipeline(first_db)
    first_executor = first_pipeline.executor
    second_pipeline = runtime.get_signal_pipeline(second_db)
    second_executor = second_pipeline.executor

    assert second_executor is not first_executor
    assert second_executor.db is second_db
    assert second_executor.user_repo.session is second_db
    assert second_executor.trade_repo.session is second_db
    assert second_executor.execution_provider is provider
