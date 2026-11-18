"""P11.4: rate limit, traces sem outputs, request_id no SQL e logs (SPEC-006 §6 e §7, 7 e 8)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import pytest
from atlas_mcp import observability, server, sql_client
from atlas_mcp.errors import InvalidArgument
from atlas_mcp.observability import Observer, RateLimited, RateLimiter
from fastmcp import Client
from fastmcp.exceptions import ToolError

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class FakeSpan:
    """Só aceita atributos: não existe set_outputs/set_inputs, então um vazamento falharia."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.attributes: dict[str, Any] = {}
        self.closed_with: BaseException | None = None

    def set_attributes(self, attributes: Mapping[str, Any]) -> None:
        self.attributes.update(attributes)


class Spans:
    def __init__(self) -> None:
        self.spans: list[FakeSpan] = []

    def __call__(self, name: str) -> Any:
        span = FakeSpan(name)
        self.spans.append(span)

        @contextmanager
        def manager() -> Iterator[FakeSpan]:
            try:
                yield span
            except BaseException as exc:
                span.closed_with = exc
                raise

        return manager()


def test_limiter_blocks_the_31st_call_and_frees_after_the_window() -> None:
    clock = Clock()
    limiter = RateLimiter(clock=clock)
    for i in range(30):
        limiter.check("ana", f"r{i}")
    with pytest.raises(RateLimited) as info:
        limiter.check("ana", "r31")
    assert info.value.retry_after_s == 60 and info.value.request_id == "r31"
    assert info.value.render().startswith("RATE_LIMITED: ")
    assert "retry_after_s=60" in str(info.value) and "request_id=r31" in str(info.value)
    limiter.check("bia", "r1")  # outro usuário não é afetado
    clock.now += 59
    with pytest.raises(RateLimited) as info:
        limiter.check("ana", "r32")
    assert info.value.retry_after_s == 1
    clock.now += 1
    limiter.check("ana", "r33")


def test_rejected_calls_do_not_extend_the_block() -> None:
    clock = Clock()
    limiter = RateLimiter(calls=2, window_s=10, clock=clock)
    limiter.check("u", "1")
    limiter.check("u", "2")
    for _ in range(5):
        clock.now += 1
        with pytest.raises(RateLimited):
            limiter.check("u", "x")
    clock.now = 1010
    limiter.check("u", "3")


def test_31st_query_metric_call_is_rate_limited_and_never_reaches_the_warehouse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executed: list[str] = []

    def make(_headers: Any) -> Any:
        def run(sql: str, _params: Any) -> Any:
            executed.append(sql)
            return ["uf", "gross_revenue"], [["SP", "1.00"]]

        return run

    monkeypatch.setattr(server, "make_executor", make)
    monkeypatch.setattr(server, "get_http_headers", lambda: {"x-forwarded-email": "ana@x.com"})
    args = {
        "view": "mv_recharges",
        "measures": ["gross_revenue"],
        "dimensions": ["uf"],
        "month_from": "2026-10",
        "month_to": "2026-10",
    }

    async def run_all() -> str:
        async with Client(server.mcp) as client:
            for _ in range(30):
                await client.call_tool("query_metric", args)
            assert len(executed) == 30
            with pytest.raises(ToolError) as info:
                await client.call_tool("query_metric", args)
            return str(info.value)

    message = asyncio.run(run_all())
    assert message.startswith("RATE_LIMITED: ") and "retry_after_s=" in message
    rid = re.search(rf"request_id=({UUID})", message)
    assert rid is not None
    assert len(executed) == 30  # o conector não foi chamado na 31ª
    assert all(rid.group(1) not in sql for sql in executed)


def test_every_tool_call_opens_a_span_with_attributes_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spans = Spans()
    observer = Observer(spans=spans, clock=Clock())
    out = observer.run(
        "query_metric",
        {"x-forwarded-email": "ana@x.com"},
        lambda rid: {"rows": [["SP", "9999.99"]] * 3, "sql_fingerprint": "abc"},
    )
    assert out["rows"][0] == ["SP", "9999.99"]
    (span,) = spans.spans
    assert span.name == "query_metric"
    assert set(span.attributes) == {
        "request_id",
        "user",
        "tool",
        "app_version",
        "sql_fingerprint",
        "rows",
        "error_code",
        "duration_ms",
    }
    assert span.attributes["user"] == "ana@x.com" and span.attributes["rows"] == 3
    assert span.attributes["sql_fingerprint"] == "abc" and span.attributes["error_code"] == ""
    assert re.fullmatch(UUID, span.attributes["request_id"])
    # Nenhum valor de resultado entra no trace.
    assert "9999.99" not in json.dumps(span.attributes, default=str)
    assert not hasattr(span, "outputs") and not hasattr(span, "set_outputs")


def test_error_code_goes_to_the_span_and_the_error_still_propagates() -> None:
    spans = Spans()
    observer = Observer(spans=spans)

    def boom(_rid: str) -> dict[str, Any]:
        raise InvalidArgument("medida fora da lista")

    with pytest.raises(InvalidArgument):
        observer.run("top_regions", {}, boom)
    (span,) = spans.spans
    assert span.attributes["error_code"] == "INVALID_ARGUMENT"
    assert span.attributes["user"] == "unknown" and "rows" not in span.attributes

    def crash(_rid: str) -> dict[str, Any]:
        raise ValueError("bug")

    with pytest.raises(ValueError, match="bug"):
        observer.run("top_regions", {}, crash)
    assert spans.spans[1].attributes["error_code"] == "INTERNAL"


def test_rate_limited_call_is_traced_and_skips_the_tool() -> None:
    spans = Spans()
    observer = Observer(limiter=RateLimiter(calls=1), spans=spans)
    called: list[str] = []

    def tool(rid: str) -> dict[str, Any]:
        called.append(rid)
        return {}

    observer.run("health", {}, tool)
    with pytest.raises(RateLimited):
        observer.run("health", {}, tool)
    assert len(called) == 1
    assert spans.spans[1].attributes["error_code"] == "RATE_LIMITED"


def test_tracing_failures_never_break_the_tool() -> None:
    def broken(_name: str) -> Any:
        raise RuntimeError("mlflow fora do ar")

    observer = Observer(spans=broken)
    assert observer.run("health", {}, lambda rid: {"status": "healthy"}) == {"status": "healthy"}

    class BadSpan(FakeSpan):
        def set_attributes(self, attributes: Mapping[str, Any]) -> None:
            raise RuntimeError("falha ao gravar")

    @contextmanager
    def bad_span(name: str) -> Iterator[BadSpan]:
        yield BadSpan(name)

    assert Observer(spans=bad_span).run("health", {}, lambda rid: {"ok": 1}) == {"ok": 1}


def test_structured_log_has_the_documented_keys_and_no_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    observer = Observer(spans=observability._noop_span)
    with caplog.at_level(logging.INFO, logger="atlas_mcp"):
        observer.run(
            "query_metric",
            {"x-forwarded-email": "ana@x.com"},
            lambda rid: {"rows": [["SP", "9999.99"]], "sql_fingerprint": "f1"},
        )
    record = json.loads(caplog.records[-1].getMessage())
    assert set(record) == {
        "request_id",
        "tool",
        "user",
        "duration_ms",
        "rows",
        "sql_fingerprint",
        "error_code",
    }
    assert record["tool"] == "query_metric" and record["rows"] == 1
    assert "9999.99" not in caplog.text


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
            {"measure": "gross_revenue", "month_a": "2026-09", "month_b": "2026-10", "level": "uf"},
        ),
    ],
)
def test_sql_carries_the_request_id_of_the_trace(
    monkeypatch: pytest.MonkeyPatch, tool: str, args: dict[str, Any]
) -> None:
    spans = Spans()
    monkeypatch.setattr(server, "observer", Observer(spans=spans))
    seen: list[str] = []

    def make(_headers: Any) -> Any:
        def run(sql: str, _params: Any) -> Any:
            seen.append(sql)
            return ["x"], []

        return run

    monkeypatch.setattr(server, "make_executor", make)
    monkeypatch.setattr(server, "get_http_headers", dict)

    async def call() -> None:
        async with Client(server.mcp) as client:
            await client.call_tool(tool, args)

    asyncio.run(call())
    rid = spans.spans[0].attributes["request_id"]
    assert seen and all(sql.startswith(f"/* atlas-mcp request_id={rid} */") for sql in seen)


@pytest.mark.parametrize("tool", ["health", "list_metrics"])
def test_non_query_tools_are_traced_too(monkeypatch: pytest.MonkeyPatch, tool: str) -> None:
    spans = Spans()
    monkeypatch.setattr(server, "observer", Observer(spans=spans))
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)

    async def call() -> None:
        async with Client(server.mcp) as client:
            await client.call_tool(tool, {})

    asyncio.run(call())
    assert [s.name for s in spans.spans] == [tool]
    assert spans.spans[0].attributes["tool"] == tool


def test_configure_tracing_is_a_noop_without_experiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MLFLOW_EXPERIMENT_ID", raising=False)
    assert observability.configure_tracing() is observability._noop_span


def test_user_of_prefers_email_header() -> None:
    assert observability.user_of({"x-forwarded-email": "a@x.com"}) == "a@x.com"
    assert observability.user_of({sql_client.TOKEN_HEADER: "tok"}) == "unknown"
