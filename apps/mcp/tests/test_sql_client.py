"""P11.2: token do usuário (OBO) e binds separados do SQL em `sql_client`."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest
from atlas_mcp import sql_client


def test_user_token_from_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_APP_NAME", "atlas-mcp")
    assert sql_client.user_token({sql_client.TOKEN_HEADER: "abc"}) == "abc"


def test_user_token_missing_inside_app_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_APP_NAME", "atlas-mcp")
    with pytest.raises(sql_client.MissingUserToken):
        sql_client.user_token({})


def test_user_token_outside_app_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    assert sql_client.user_token({}) is None


def test_executor_passes_params_separately_from_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "wh1")
    monkeypatch.setenv("DATABRICKS_HOST", "https://example.cloud.databricks.com/")
    seen: dict[str, Any] = {}

    class Cursor:
        description = (("uf",), ("gross_revenue",))

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def execute(self, sql: str, params: dict[str, Any]) -> None:
            seen["sql"], seen["params"] = sql, params

        def fetchall(self) -> list[tuple[str, str]]:
            return [("SP", "1.00")]

    class Conn(Cursor):
        def cursor(self) -> Cursor:
            return Cursor()

    def connect(**kw: Any) -> Conn:
        seen["connect"] = kw
        return Conn()

    pkg = ModuleType("databricks")
    mod = ModuleType("databricks.sql")
    mod.connect = connect  # type: ignore[attr-defined]
    pkg.sql = mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "databricks.sql", mod)
    monkeypatch.setattr("databricks.sql", mod, raising=False)

    run = sql_client.make_executor({sql_client.TOKEN_HEADER: "tok"})
    columns, rows = run("SELECT :f0", {"f0": "x'; DROP"})
    assert (columns, rows) == (["uf", "gross_revenue"], [["SP", "1.00"]])
    assert seen["sql"] == "SELECT :f0" and seen["params"] == {"f0": "x'; DROP"}
    assert seen["connect"]["server_hostname"] == "example.cloud.databricks.com"
    assert seen["connect"]["access_token"] == "tok"  # noqa: S105
