from __future__ import annotations

import threading
from typing import Any

import pytest
from atlas_web.sql_client import ConnectionExecutor


class FakeCursor:
    description = (("a",),)

    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        self.conn.executed.append((sql, params))
        if self.conn.fail:
            raise ConnectionError("conexão caiu")

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]


class FakeConn:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.closed = False
        self.executed: list[tuple[str, dict[str, Any]]] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True


class Factory:
    def __init__(self, *conns: FakeConn) -> None:
        self.conns = list(conns)
        self.opened: list[FakeConn] = []
        self.lock = threading.Lock()

    def __call__(self) -> FakeConn:
        with self.lock:
            conn = self.conns.pop(0) if self.conns else FakeConn()
            self.opened.append(conn)
            return conn


def test_reuses_the_connection_in_the_same_thread() -> None:
    factory = Factory()
    execute = ConnectionExecutor(factory)
    assert execute("SELECT 1", {"m": 1}) == (["a"], [[1]])
    execute("SELECT 2", {})
    assert len(factory.opened) == 1
    assert [s for s, _ in factory.opened[0].executed] == ["SELECT 1", "SELECT 2"]
    assert factory.opened[0].executed[0][1] == {"m": 1}


def test_reconnects_once_when_a_reused_connection_fails() -> None:
    stale = FakeConn()
    factory = Factory(stale)
    execute = ConnectionExecutor(factory)
    execute("SELECT 1", {})
    stale.fail = True
    assert execute("SELECT 2", {}) == (["a"], [[1]])
    assert stale.closed
    assert len(factory.opened) == 2
    execute("SELECT 3", {})
    assert len(factory.opened) == 2  # a nova conexão também é reaproveitada


def test_fresh_connection_failure_is_not_retried() -> None:
    bad = FakeConn(fail=True)
    factory = Factory(bad)
    execute = ConnectionExecutor(factory)
    with pytest.raises(ConnectionError):
        execute("SELECT 1", {})
    assert bad.closed
    assert len(bad.executed) == 1
    execute("SELECT 2", {})  # a próxima consulta abre outra
    assert len(factory.opened) == 2


def test_reconnect_that_fails_again_propagates() -> None:
    stale = FakeConn()
    factory = Factory(stale, FakeConn(fail=True))
    execute = ConnectionExecutor(factory)
    execute("SELECT 1", {})
    stale.fail = True
    with pytest.raises(ConnectionError):
        execute("SELECT 2", {})
    assert len(factory.opened) == 2  # uma nova tentativa só


def test_each_thread_gets_its_own_connection() -> None:
    factory = Factory()
    execute = ConnectionExecutor(factory)
    execute("SELECT 1", {})
    seen: list[int] = []

    def work() -> None:
        execute("SELECT 2", {})
        execute("SELECT 3", {})
        seen.append(len(factory.opened))

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert len(factory.opened) == 2
    assert len(factory.opened[1].executed) == 2
    assert len(factory.opened[0].executed) == 1


def test_close_errors_are_ignored_on_reconnect() -> None:
    class BadClose(FakeConn):
        def close(self) -> None:
            raise RuntimeError("já fechada")

    stale = BadClose()
    execute = ConnectionExecutor(Factory(stale))
    execute("SELECT 1", {})
    stale.fail = True
    assert execute("SELECT 2", {}) == (["a"], [[1]])


def test_close_thread_closes_only_the_current_threads_connection() -> None:
    factory = Factory()
    execute = ConnectionExecutor(factory)
    execute("SELECT 1", {})
    execute.close_thread()
    assert factory.opened[0].closed
    execute("SELECT 2", {})
    assert len(factory.opened) == 2
