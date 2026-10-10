import pytest

from database import db_persistence


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _Connection:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.statements = []
        self.closed = False

    def execute(self, statement, params):
        self.statements.append((str(statement), params))
        return _Result(self.acquired if "pg_try_advisory_lock" in str(statement) else True)

    def close(self):
        self.closed = True


class _Engine:
    class _Dialect:
        name = "postgresql"

    dialect = _Dialect()

    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


def test_postgres_persistence_lock_is_held_until_shutdown(monkeypatch):
    connection = _Connection(acquired=True)
    monkeypatch.setattr(db_persistence.db_manager, "engine", _Engine(connection))
    persistence = db_persistence.DBPersistence()

    persistence.acquire_single_instance_lock()
    assert persistence._instance_lock_connection is connection
    persistence.release_single_instance_lock()

    assert connection.closed is True
    assert len(connection.statements) == 2
    assert "pg_try_advisory_lock" in connection.statements[0][0]
    assert "pg_advisory_unlock" in connection.statements[1][0]


def test_second_postgres_bot_process_fails_closed(monkeypatch):
    connection = _Connection(acquired=False)
    monkeypatch.setattr(db_persistence.db_manager, "engine", _Engine(connection))
    persistence = db_persistence.DBPersistence()

    with pytest.raises(RuntimeError, match="already owns DBPersistence"):
        persistence.acquire_single_instance_lock()

    assert connection.closed is True
    assert persistence._instance_lock_connection is None
