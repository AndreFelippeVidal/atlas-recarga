"""Observabilidade e controle do `atlas-mcp` (SPEC-006 §6): rate limit, traces e logs estruturados.

* **Rate limit:** 30 chamadas por minuto por usuário, em memória, antes de qualquer query.
* **Trace:** um span manual (`mlflow.start_span`) por chamada de tool, só com atributos. Nunca
  `@mlflow.trace` e nunca `set_outputs`/`set_inputs`: o valor das linhas não entra no trace.
* **Log:** uma linha JSON por chamada no stdout do App, para depuração.

Falha de observabilidade nunca quebra a tool: sem o `mlflow` (ou sem experiment) o span vira no-op.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Protocol

from atlas_mcp.errors import McpError
from atlas_mcp.health import app_version

log = logging.getLogger("atlas_mcp")

RATE_LIMIT_CALLS = 30  # o mesmo teto do agente (SPEC-006 §6)
RATE_LIMIT_WINDOW_S = 60.0
USER_HEADERS = ("x-forwarded-email", "x-forwarded-preferred-username", "x-forwarded-user")
UNKNOWN_USER = "unknown"


class RateLimited(McpError):
    """Mais de 30 chamadas por minuto do mesmo usuário (SPEC-006 §4). Nenhuma query é executada."""

    code = "RATE_LIMITED"

    def __init__(self, retry_after_s: int, request_id: str) -> None:
        self.retry_after_s = retry_after_s
        self.request_id = request_id
        super().__init__(
            f"limite de {RATE_LIMIT_CALLS} chamadas por minuto; "
            f"retry_after_s={retry_after_s} request_id={request_id}"
        )


class RateLimiter:
    """Janela deslizante por usuário. Só as chamadas aceitas contam; vale por instância do App."""

    def __init__(
        self,
        calls: int = RATE_LIMIT_CALLS,
        window_s: float = RATE_LIMIT_WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._calls = calls
        self._window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, user: str, request_id: str) -> None:
        now = self._clock()
        with self._lock:
            hits = self._hits[user]
            while hits and now - hits[0] >= self._window_s:
                hits.popleft()
            if len(hits) >= self._calls:
                wait = max(1, math.ceil(hits[0] + self._window_s - now))
                raise RateLimited(wait, request_id)
            hits.append(now)


class Span(Protocol):
    def set_attributes(self, attributes: Mapping[str, Any]) -> None: ...


class _NoopSpan:
    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        return None


SpanFactory = Callable[[str], Any]  # nome -> context manager que devolve um Span


def configure_tracing() -> SpanFactory:
    """Liga o MLflow ao experiment do App (`MLFLOW_EXPERIMENT_ID`); sem isso, no-op."""
    experiment_id = os.environ.get("MLFLOW_EXPERIMENT_ID")
    if not experiment_id:
        log.warning("MLFLOW_EXPERIMENT_ID ausente: traces desligados")
        return _noop_span
    try:
        import mlflow

        os.environ.setdefault("MLFLOW_TRACKING_URI", "databricks")
        mlflow.set_experiment(experiment_id=experiment_id)
    except Exception as exc:
        log.warning("traces desligados: %s", type(exc).__name__)
        return _noop_span

    def start(name: str) -> Any:
        return mlflow.start_span(name=name)

    return start


@contextmanager
def _noop_span(name: str) -> Iterator[Span]:
    yield _NoopSpan()


@contextmanager
def _safe_span(factory: SpanFactory, name: str) -> Iterator[Span]:
    """Abre o span sem deixar uma falha do MLflow derrubar a tool."""
    try:
        manager = factory(name)
        span = manager.__enter__()
    except Exception as exc:
        log.warning("span não aberto: %s", type(exc).__name__)
        yield _NoopSpan()
        return
    try:
        yield span
    except BaseException as exc:
        try:
            manager.__exit__(type(exc), exc, exc.__traceback__)
        except Exception as inner:  # a falha da tool é a que importa
            log.warning("span não fechado: %s", type(inner).__name__)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as inner:
            log.warning("span não fechado: %s", type(inner).__name__)


def user_of(headers: Mapping[str, str]) -> str:
    for name in USER_HEADERS:
        value = headers.get(name)
        if value:
            return value
    return UNKNOWN_USER


class Observer:
    """Aplica rate limit, trace e log a cada chamada de tool."""

    def __init__(
        self,
        limiter: RateLimiter | None = None,
        spans: SpanFactory | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.limiter = limiter or RateLimiter()
        self._spans = spans
        self._clock = clock

    def _factory(self) -> SpanFactory:
        if self._spans is None:
            self._spans = configure_tracing()
        return self._spans

    def run(
        self,
        tool: str,
        headers: Mapping[str, str],
        call: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        """Roda `call(request_id)`. O limite vem antes: estourado, `call` nem é chamado."""
        request_id = str(uuid.uuid4())
        user = user_of(headers)
        started = self._clock()
        attrs: dict[str, Any] = {
            "request_id": request_id,
            "user": user,
            "tool": tool,
            "app_version": app_version(),
            "error_code": "",
        }
        try:
            with _safe_span(self._factory(), tool) as span:
                try:
                    self.limiter.check(user, request_id)
                    result = call(request_id)
                    rows = result.get("rows")
                    attrs["rows"] = len(rows) if isinstance(rows, list) else 0
                    attrs["sql_fingerprint"] = str(result.get("sql_fingerprint", ""))
                    return result
                except McpError as exc:
                    attrs["error_code"] = exc.code
                    raise
                except Exception:
                    attrs["error_code"] = "INTERNAL"
                    raise
                finally:
                    attrs["duration_ms"] = round((self._clock() - started) * 1000)
                    try:
                        span.set_attributes(attrs)
                    except Exception as exc:
                        log.warning("atributos do span não gravados: %s", type(exc).__name__)
        finally:
            attrs.setdefault("duration_ms", round((self._clock() - started) * 1000))
            log.info(json.dumps(_log_record(attrs), sort_keys=True))


def _log_record(attrs: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("request_id", "tool", "user", "duration_ms", "rows", "sql_fingerprint", "error_code")
    return {k: attrs[k] for k in keys if k in attrs}
