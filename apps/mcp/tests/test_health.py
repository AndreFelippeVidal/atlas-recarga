"""P11.1: critério 1 da SPEC-006 §7 e o formato do `health` (§3)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from atlas_mcp import health as health_mod
from atlas_mcp.server import mcp
from fastmcp import Client


def _fetch(value: str) -> Any:
    return lambda _id: SimpleNamespace(state=SimpleNamespace(value=value))


def test_health_reports_warehouse_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "abc")
    result = health_mod.health(_fetch("RUNNING"))
    assert result["status"] == "healthy"
    assert result["warehouse"] == "RUNNING"
    assert result["version"]


def test_health_without_warehouse_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    assert health_mod.health()["warehouse"] == health_mod.UNKNOWN


def test_health_survives_warehouse_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "abc")

    def boom(_id: str) -> Any:
        raise RuntimeError("token secreto no stack trace")

    result = health_mod.health(boom)
    assert result == {
        "status": "healthy",
        "warehouse": health_mod.UNREACHABLE,
        "version": health_mod.app_version(),
    }


def test_mcp_client_calls_health(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)

    async def run() -> Any:
        async with Client(mcp) as client:
            names = {t.name for t in await client.list_tools()}
            return names, await client.call_tool("health", {})

    names, result = asyncio.run(run())
    assert "health" in names
    assert result.data["status"] == "healthy"


def test_main_serves_streamable_http_on_app_port(monkeypatch: pytest.MonkeyPatch) -> None:
    from atlas_mcp import server

    calls: list[dict[str, Any]] = []
    monkeypatch.setenv("DATABRICKS_APP_PORT", "8123")
    monkeypatch.setattr(server.mcp, "run", lambda **kw: calls.append(kw))
    server.main()
    assert calls == [
        {"transport": "streamable-http", "host": "0.0.0.0", "port": 8123, "path": "/mcp"}  # noqa: S104
    ]
