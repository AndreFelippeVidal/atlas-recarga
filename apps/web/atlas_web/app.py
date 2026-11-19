"""FastAPI do `atlas-web`: `/api/months`, `/api/kpis`, `/api/map/*`, `/api/health` (SPEC-007 §3)."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from atlas_web import kpis as kpis_mod
from atlas_web import map_data
from atlas_web.cache import TTLCache
from atlas_web.sql_client import Executor, make_executor

log = logging.getLogger(__name__)
UNKNOWN = "UNKNOWN"
UNREACHABLE = "UNREACHABLE"
RETRY_TIMEOUT_S = 10
WARM_WORKERS = 4
REFRESH_INTERVAL_S = 480  # antes do TTL de 10 min do cache (SPEC-007 §3)


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


Task = tuple[tuple[Any, ...], Callable[[], Any]]


def warm_tasks(catalog: str, run: Executor, month: str) -> list[Task]:
    """Consultas da tela do mês, com as mesmas chaves de cache dos endpoints."""
    tasks: list[Task] = [(("kpis", month), lambda: kpis_mod.kpis(catalog, run, month))]
    for measure in map_data.MAP_MEASURES:
        tasks.append(
            (
                ("map", "region", month, measure),
                partial(map_data.map_region, catalog, run, month, measure),
            )
        )
        tasks.append(
            (
                ("map", "uf", month, measure, None),
                partial(map_data.map_uf, catalog, run, month, measure, None),
            )
        )
    return tasks


def warm_cache(
    store: TTLCache, catalog: str, run: Executor, release: Callable[[], None] | None = None
) -> None:
    """Aquece (ou renova) o cache da tela do último mês, em paralelo. Nunca levanta.

    Cada consulta que falha é registrada e o valor antigo do cache fica.
    """

    def one(key: tuple[Any, ...], compute: Callable[[], Any]) -> None:
        try:
            store.refresh(key, compute)
        except Exception:
            log.warning("aquecimento falhou para %s", key, exc_info=True)
        finally:
            if release is not None:  # a thread do pool morre no fim do ciclo: não vaza conexão
                release()

    try:
        months = store.refresh(("months",), lambda: kpis_mod.list_months(catalog, run))
    except Exception:
        log.warning("aquecimento falhou: meses", exc_info=True)
        return
    finally:
        if release is not None:
            release()
    if not months:
        return
    with ThreadPoolExecutor(max_workers=WARM_WORKERS) as pool:
        for key, compute in warm_tasks(catalog, run, months[0]):
            pool.submit(one, key, compute)


def create_app(
    executor: Executor | None = None,
    cache: TTLCache | None = None,
    warehouse_fetch: Callable[[str], Any] | None = None,
    warm: bool = True,
    refresh_interval_s: float = REFRESH_INTERVAL_S,
) -> FastAPI:
    store = cache or TTLCache()
    catalog = os.environ.get("ATLAS_CATALOG", "atlas")
    holder: list[Executor] = [executor] if executor else []
    holder_lock = threading.Lock()

    def run(sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        if not holder:  # o executor só nasce na 1ª consulta (precisa do ambiente do App)
            with holder_lock:
                if not holder:
                    holder.append(make_executor())
        return holder[0](sql, params)

    def release() -> None:
        close = getattr(holder[0], "close_thread", None) if holder else None
        if close is not None:
            close()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()

        def loop() -> None:  # thread daemon: aquece na subida e renova antes do TTL
            while not stop.is_set():
                warm_cache(store, catalog, run, release)
                stop.wait(refresh_interval_s)

        if warm:
            threading.Thread(target=loop, name="cache-warmer", daemon=True).start()
        try:
            yield
        finally:
            stop.set()

    app = FastAPI(title="atlas-web", docs_url=None, redoc_url=None, lifespan=lifespan)

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

    def invalid(exc: Exception) -> HTTPException:
        return HTTPException(400, {"code": "INVALID_ARGUMENT", "message": str(exc)})

    def serve(key: tuple[Any, ...], compute: Callable[[], list[dict[str, Any]]]) -> Any:
        try:
            return store.get_or_set(key, compute)
        except kpis_mod.MonthNotFound:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "mês sem dados"}) from None
        except Exception:
            log.exception("consulta falhou")
            raise unavailable() from None

    @app.get("/api/map/region")
    def map_region(month: str = Query(...), measure: str = Query(...)) -> list[dict[str, Any]]:
        try:
            kpis_mod.parse_month(month)
            map_data.check_measure(measure)
        except (kpis_mod.InvalidMonth, map_data.InvalidArgument) as exc:
            raise invalid(exc) from None
        result: list[dict[str, Any]] = serve(
            ("map", "region", month, measure),
            lambda: map_data.map_region(catalog, run, month, measure),
        )
        return result

    @app.get("/api/map/uf")
    def map_uf(
        month: str = Query(...), measure: str = Query(...), region: str | None = Query(None)
    ) -> list[dict[str, Any]]:
        try:
            kpis_mod.parse_month(month)
            map_data.check_measure(measure)
            if region is not None:
                map_data.check_region(region)
        except (kpis_mod.InvalidMonth, map_data.InvalidArgument) as exc:
            raise invalid(exc) from None
        result: list[dict[str, Any]] = serve(
            ("map", "uf", month, measure, region),
            lambda: map_data.map_uf(catalog, run, month, measure, region),
        )
        return result

    @app.get("/api/map/municipality")
    def map_municipality(
        month: str = Query(...), measure: str = Query(...), uf: str | None = Query(None)
    ) -> list[dict[str, Any]]:
        try:
            kpis_mod.parse_month(month)
            map_data.check_measure(measure)
            map_data.check_uf(uf or "")
        except (kpis_mod.InvalidMonth, map_data.InvalidArgument) as exc:
            raise invalid(exc) from None
        result: list[dict[str, Any]] = serve(
            ("map", "municipality", month, measure, uf),
            lambda: map_data.map_municipality(catalog, run, month, measure, uf or ""),
        )
        return result

    return app
