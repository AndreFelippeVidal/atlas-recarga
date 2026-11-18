"""P11.3: contrato de erros da SPEC-006 §4 (sem RATE_LIMITED, que é da P11.4)."""

from __future__ import annotations

import asyncio
import sys
import time
from types import ModuleType
from typing import Any

import pytest
from atlas_mcp import server, sql_client
from atlas_mcp.errors import (
    InvalidArgument,
    PermissionDenied,
    ResultTooLarge,
    WarehouseUnavailable,
    classify,
)
from fastmcp import Client
from fastmcp.exceptions import ToolError


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            RuntimeError("[INSUFFICIENT_PERMISSIONS] User does not have SELECT on table"),
            PermissionDenied,
        ),
        (RuntimeError("PERMISSION_DENIED: nope"), PermissionDenied),
        (TimeoutError("read timed out"), WarehouseUnavailable),
        (RuntimeError("MaxRetryError: host=segredo.cloud.databricks.com"), WarehouseUnavailable),
        (RuntimeError("TEMPORARILY_UNAVAILABLE: warehouse is starting"), WarehouseUnavailable),
        (InvalidArgument("x"), InvalidArgument),
        (ResultTooLarge("x"), ResultTooLarge),
    ],
)
def test_classify_maps_known_failures(exc: Exception, expected: type) -> None:
    assert isinstance(classify(exc), expected)


def test_classify_unknown_is_none_and_messages_are_fixed() -> None:
    assert classify(ValueError("outra coisa")) is None
    known = classify(RuntimeError("PERMISSION_DENIED token=abc host=h"))
    assert known is not None and "abc" not in str(known) and "host" not in str(known)


def test_codes_are_prefixed() -> None:
    assert InvalidArgument("m").render() == "INVALID_ARGUMENT: m"
    assert PermissionDenied("m").code == "PERMISSION_DENIED"
    assert WarehouseUnavailable("m").code == "WAREHOUSE_UNAVAILABLE"
    assert ResultTooLarge("m").code == "RESULT_TOO_LARGE"


def _fake_connector(monkeypatch: pytest.MonkeyPatch, outcomes: list[Exception | None]) -> list[int]:
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh1")
    monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com/")
    calls: list[int] = []

    class Cursor:
        description = (("uf",),)

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def execute(self, _sql: str, _params: dict[str, Any]) -> None:
            calls.append(1)
            outcome = outcomes[len(calls) - 1]
            if outcome is not None:
                raise outcome

        def fetchall(self) -> list[tuple[str]]:
            return [("SP",)]

    class Conn(Cursor):
        def cursor(self) -> Cursor:
            return Cursor()

    mod = ModuleType("databricks.sql")
    mod.connect = lambda **_kw: Conn()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "databricks.sql", mod)
    monkeypatch.setattr("databricks.sql", mod, raising=False)
    return calls


def test_warehouse_unavailable_retries_once_after_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_connector(monkeypatch, [TimeoutError("timed out"), None])
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    run = sql_client.make_executor({sql_client.TOKEN_HEADER: "tok"})
    assert run("SELECT 1", {}) == (["uf"], [["SP"]])
    assert len(calls) == 2 and sleeps == [20]


def test_warehouse_unavailable_after_second_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_connector(monkeypatch, [TimeoutError("a"), TimeoutError("b")])
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    run = sql_client.make_executor({sql_client.TOKEN_HEADER: "tok"})
    with pytest.raises(WarehouseUnavailable):
        run("SELECT 1", {})
    assert len(calls) == 2


def test_permission_denied_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_connector(monkeypatch, [RuntimeError("INSUFFICIENT_PERMISSIONS"), None])
    monkeypatch.setattr(time, "sleep", lambda _s: pytest.fail("não deve esperar"))
    run = sql_client.make_executor({sql_client.TOKEN_HEADER: "tok"})
    with pytest.raises(PermissionDenied):
        run("SELECT 1", {})
    assert len(calls) == 1


def test_unknown_failure_is_reraised_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_connector(monkeypatch, [ValueError("bug")])
    run = sql_client.make_executor({sql_client.TOKEN_HEADER: "tok"})
    with pytest.raises(ValueError, match="bug"):
        run("SELECT 1", {})


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (PermissionDenied("sem SELECT"), "PERMISSION_DENIED"),
        (WarehouseUnavailable("parado"), "WAREHOUSE_UNAVAILABLE"),
    ],
)
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (
            "query_metric",
            {
                "view": "mv_recharges",
                "measures": ["gross_revenue"],
                "month_from": "2026-10",
                "month_to": "2026-10",
            },
        ),
        ("top_regions", {"measure": "gross_revenue", "level": "uf", "month": "2026-10"}),
        (
            "compare_months",
            {
                "measure": "gross_revenue",
                "month_a": "2026-09",
                "month_b": "2026-10",
                "level": "uf",
            },
        ),
    ],
)
def test_tools_surface_standard_codes_without_stack_trace(
    monkeypatch: pytest.MonkeyPatch, raised: Exception, code: str, tool: str, args: dict[str, Any]
) -> None:
    def failing(_headers: Any) -> Any:
        def run(_sql: str, _params: Any) -> Any:
            raise raised

        return run

    monkeypatch.setattr(server, "make_executor", failing)

    async def call() -> str:
        async with Client(server.mcp) as client:
            with pytest.raises(ToolError) as info:
                await client.call_tool(tool, args)
            return str(info.value)

    message = asyncio.run(call())
    assert code in message and "Traceback" not in message
