"""FastAPI do `atlas-web`: `/api/months`, `/api/kpis`, `/api/map/*`, `/api/health` (SPEC-007 §3)."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncIterator, Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from atlas_web import chat, map_data
from atlas_web import filters as filters_mod
from atlas_web import kpis as kpis_mod
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
    nf = filters_mod.NO_FILTERS.key
    tasks: list[Task] = [(("kpis", month, nf), lambda: kpis_mod.kpis(catalog, run, month))]
    for measure in map_data.MAP_MEASURES:
        tasks.append(
            (
                ("map", "region", month, measure, nf),
                partial(map_data.map_region, catalog, run, month, measure),
            )
        )
        tasks.append(
            (
                ("map", "uf", month, measure, None, nf),
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
    static_dir: Path | None = None,
    geo_dir: Path | None = None,
    agent_transport: httpx2.AsyncBaseTransport | None = None,
    chat_settings: chat.ChatSettings | None = None,
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

    app = FastAPI(
        title="atlas-web", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )

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

    def filter_values(*, reread: bool = False) -> dict[str, list[str]]:
        key = ("filters",)
        compute = partial(filters_mod.list_filters, catalog, run)
        try:
            values: dict[str, list[str]] = (
                store.refresh(key, compute) if reread else store.get_or_set(key, compute)
            )
            return values
        except Exception:
            log.exception("consulta falhou")
            raise unavailable() from None

    def checked_filters(pos_type: str | None, distributor: str | None) -> filters_mod.Filters:
        """Valida os filtros; um distribuidor fora do cache força **uma** releitura antes do 400."""
        if pos_type is not None:
            filters_mod.check_pos_type(pos_type)
        if (
            distributor is not None
            and distributor not in filter_values()["distributors"]
            and distributor not in filter_values(reread=True)["distributors"]
        ):
            raise filters_mod.InvalidFilter("distributor deve ser um valor de /api/filters")
        return filters_mod.Filters(pos_type, distributor)

    @app.get("/api/filters")
    def filters() -> dict[str, list[str]]:
        return filter_values()

    @app.get("/api/kpis")
    def kpis(
        month: str = Query(...),
        pos_type: str | None = Query(None),
        distributor: str | None = Query(None),
    ) -> dict[str, Any]:
        try:
            kpis_mod.parse_month(month)
            flt = checked_filters(pos_type, distributor)
        except (kpis_mod.InvalidMonth, filters_mod.InvalidFilter) as exc:
            raise HTTPException(400, {"code": "INVALID_ARGUMENT", "message": str(exc)}) from None
        try:
            result: dict[str, Any] = store.get_or_set(
                ("kpis", month, flt.key), lambda: kpis_mod.kpis(catalog, run, month, flt)
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
    def map_region(
        month: str = Query(...),
        measure: str = Query(...),
        pos_type: str | None = Query(None),
        distributor: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        try:
            kpis_mod.parse_month(month)
            map_data.check_measure(measure)
            flt = checked_filters(pos_type, distributor)
        except (kpis_mod.InvalidMonth, map_data.InvalidArgument, filters_mod.InvalidFilter) as exc:
            raise invalid(exc) from None
        result: list[dict[str, Any]] = serve(
            ("map", "region", month, measure, flt.key),
            lambda: map_data.map_region(catalog, run, month, measure, flt),
        )
        return result

    @app.get("/api/map/uf")
    def map_uf(
        month: str = Query(...),
        measure: str = Query(...),
        region: str | None = Query(None),
        pos_type: str | None = Query(None),
        distributor: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        try:
            kpis_mod.parse_month(month)
            map_data.check_measure(measure)
            if region is not None:
                map_data.check_region(region)
            flt = checked_filters(pos_type, distributor)
        except (kpis_mod.InvalidMonth, map_data.InvalidArgument, filters_mod.InvalidFilter) as exc:
            raise invalid(exc) from None
        result: list[dict[str, Any]] = serve(
            ("map", "uf", month, measure, region, flt.key),
            lambda: map_data.map_uf(catalog, run, month, measure, region, flt),
        )
        return result

    @app.get("/api/map/municipality")
    def map_municipality(
        month: str = Query(...),
        measure: str = Query(...),
        uf: str | None = Query(None),
        pos_type: str | None = Query(None),
        distributor: str | None = Query(None),
    ) -> list[dict[str, Any]]:
        try:
            kpis_mod.parse_month(month)
            map_data.check_measure(measure)
            map_data.check_uf(uf or "")
            flt = checked_filters(pos_type, distributor)
        except (kpis_mod.InvalidMonth, map_data.InvalidArgument, filters_mod.InvalidFilter) as exc:
            raise invalid(exc) from None
        result: list[dict[str, Any]] = serve(
            ("map", "municipality", month, measure, uf, flt.key),
            lambda: map_data.map_municipality(catalog, run, month, measure, uf or "", flt),
        )
        return result

    settings = chat_settings or chat.ChatSettings()
    limiter = chat.RateLimiter(settings.rate_limit, settings.rate_window_s)

    @app.post("/api/chat")
    async def chat_route(request: Request) -> StreamingResponse:
        """Repassa a pergunta ao `agent-atlas` como o usuário e devolve SSE (ADR-0023)."""
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        message, conversation_id = chat.parse_body(payload)
        token = request.headers.get(chat.TOKEN_HEADER)
        if not token:  # sem o token do usuário não há OBO: o SP nunca fala pelo usuário
            raise chat.error_http(403, "PERMISSION_DENIED", "sem identidade do usuário")
        if not limiter.allow(chat.user_key(request, token)):
            raise HTTPException(
                429,
                {"code": "RATE_LIMITED", "message": "limite de mensagens por minuto atingido"},
                headers={"Retry-After": str(int(settings.rate_window_s))},
            )
        agent_url = os.environ.get("ATLAS_AGENT_URL")
        if not agent_url:
            raise chat.error_http(503, "AGENT_UNAVAILABLE", "o agente não está configurado")
        client = httpx2.AsyncClient(
            transport=agent_transport,
            timeout=httpx2.Timeout(
                settings.total_timeout_s,
                connect=settings.connect_timeout_s,
                read=settings.idle_timeout_s,
            ),
        )
        try:
            response = await chat.open_agent_stream(
                client, agent_url, token, message, conversation_id
            )
        except chat.AgentRateLimited:
            await client.aclose()
            return chat.immediate_error("RATE_LIMITED", "limite de uso do agente atingido")
        except HTTPException:
            await client.aclose()
            raise

        async def body() -> Any:
            try:
                async for event in chat.stream_events(response, settings):
                    yield event
            finally:
                await client.aclose()

        return StreamingResponse(body(), media_type="text/event-stream", headers=chat.SSE_HEADERS)

    mount_frontend(app, static_dir, geo_dir)
    return app


def mount_frontend(app: FastAPI, static_dir: Path | None, geo_dir: Path | None) -> None:
    """Serve o build do React e as malhas do mapa (SPEC-007 §2). Vem depois de `/api/*`."""
    if geo_dir is not None and geo_dir.is_dir():
        app.mount("/geo", StaticFiles(directory=geo_dir), name="geo")
    if static_dir is None:
        return
    if not (static_dir / "index.html").is_file():
        log.warning("build do React ausente em %s: o App serve só a API", static_dir)
        return
    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
    index = static_dir / "index.html"

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
