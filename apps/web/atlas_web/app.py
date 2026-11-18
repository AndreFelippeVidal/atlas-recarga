"""FastAPI do `atlas-web`: `/api/months`, `/api/kpis`, `/api/health` (SPEC-007 §3)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from atlas_web import kpis as kpis_mod
from atlas_web.cache import TTLCache
from atlas_web.sql_client import Executor, make_executor

log = logging.getLogger(__name__)
UNKNOWN = "UNKNOWN"
UNREACHABLE = "UNREACHABLE"
RETRY_TIMEOUT_S = 10


def warehouse_state(warehouse_id: str | None, fetch: Callable[[str], Any] | None = None) -> str:
    """Estado do warehouse sem acordá-lo. Nunca levanta: o health tem que responder."""
    if not warehouse_id:
        return UNKNOWN
    try:
        if fetch is None:
            from databricks.sdk import WorkspaceClient
            from databricks.sdk.core import Config

            fetch = WorkspaceClient(
                config=Config(retry_timeout_seconds=RETRY_TIMEOUT_S)
            ).warehouses.get
        state = fetch(warehouse_id).state
        return str(getattr(state, "value", state) or UNKNOWN)
    except Exception:
        return UNREACHABLE


def create_app(
    executor: Executor | None = None,
    cache: TTLCache | None = None,
    warehouse_fetch: Callable[[str], Any] | None = None,
) -> FastAPI:
    app = FastAPI(title="atlas-web", docs_url=None, redoc_url=None)
    store = cache or TTLCache()
    catalog = os.environ.get("ATLAS_CATALOG", "atlas")
    holder: list[Executor] = [executor] if executor else []

    def run(sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        if not holder:  # o executor só nasce na 1ª consulta (precisa do ambiente do App)
            holder.append(make_executor())
        return holder[0](sql, params)

    def unavailable() -> HTTPException:
        return HTTPException(503, {"code": "WAREHOUSE_UNAVAILABLE", "message": "consulta falhou"})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {
            "status": "healthy",
            "warehouse": warehouse_state(
                os.environ.get("DATABRICKS_WAREHOUSE_ID"), warehouse_fetch
            ),
        }

    @app.get("/api/months")
    def months() -> dict[str, list[str]]:
        try:
            return {
                "months": store.get_or_set(("months",), lambda: kpis_mod.list_months(catalog, run))
            }
        except Exception:
            log.exception("consulta falhou")
            raise unavailable() from None

    @app.get("/api/kpis")
    def kpis(month: str = Query(...)) -> dict[str, Any]:
        try:
            kpis_mod.parse_month(month)
        except kpis_mod.InvalidMonth as exc:
            raise HTTPException(400, {"code": "INVALID_ARGUMENT", "message": str(exc)}) from None
        try:
            result: dict[str, Any] = store.get_or_set(
                ("kpis", month), lambda: kpis_mod.kpis(catalog, run, month)
            )
            return result
        except kpis_mod.MonthNotFound:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "mês sem dados"}) from None
        except Exception:
            log.exception("consulta falhou")
            raise unavailable() from None

    return app
