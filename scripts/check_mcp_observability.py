"""Confere rate limit, traces e `executed_by` do `atlas-mcp` (SPEC-006 §7, critérios 7 a 9; P11.4).

O App só existe no workspace, então o **mantenedor** roda isto depois do deploy e do
`setup_mcp_trace_tables.py`. Precisa do `mlflow` (o projeto `apps/mcp` o traz):

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_mcp -t dev --profile andrevidal
    uv run --project apps/mcp python scripts/check_mcp_observability.py --profile andrevidal \\
        --warehouse-id <id> --experiment-id <id do atlas_mcp_traces> [--mode obo]

Conecta como cliente MCP real (credencial do perfil em memória, nunca impressa):
1. chama as 5 tools uma vez cada e espera um trace por chamada em `/Shared/atlas/mcp`, com os
   atributos do §6 e sem outputs (critério 8);
2. dispara 31 `query_metric` seguidas: a 31ª devolve `RATE_LIMITED` com `retry_after_s` e
   `request_id`, e esse `request_id` não aparece na `system.query.history` (critério 7);
3. confere `executed_by` das queries com o comentário `atlas-mcp request_id=` na
   `system.query.history` (critério 9): o usuário do perfil em `--mode obo`; no plano B
   (`--mode service-principal`) um service principal diferente do usuário e o `user` do trace
   igual ao do perfil.

A `system.query.history` tem atraso de alguns minutos: o script espera até 6 min. Rode no máximo
uma vez por minuto (o limite é por usuário). Só lê, exceto as chamadas das tools.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

APP_NAME = "atlas-mcp"
TOOLS = ("health", "list_metrics", "query_metric", "top_regions", "compare_months")
SPAN_ATTRIBUTES = {"request_id", "user", "tool", "app_version", "error_code", "duration_ms"}
QUERY_TOOLS = {"query_metric", "top_regions", "compare_months"}
HISTORY_WAIT_S = 360
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_COMMENT = re.compile(r"/\* atlas-mcp request_id=(?P<rid>[0-9a-f-]{36}) \*/")


def check_spans(spans: Sequence[Mapping[str, Any]]) -> list[str]:
    """Critério 8: um span por tool, com os atributos do §6, sem outputs e sem valores."""
    problems: list[str] = []
    seen = {s.get("attributes", {}).get("tool") for s in spans}
    for tool in TOOLS:
        if tool not in seen:
            problems.append(f"sem trace para a tool {tool}")
    for span in spans:
        attrs = span.get("attributes", {})
        tool = attrs.get("tool", "?")
        missing = SPAN_ATTRIBUTES - set(attrs)
        if missing:
            problems.append(f"trace de {tool} sem atributos {sorted(missing)}")
        if tool in QUERY_TOOLS and not attrs.get("error_code") and "sql_fingerprint" not in attrs:
            problems.append(f"trace de {tool} sem sql_fingerprint")
        if span.get("outputs") not in (None, "", {}, []):
            problems.append(f"trace de {tool} tem outputs (os valores não podem entrar)")
    return problems


def check_rate_limit(results: Sequence[str | None]) -> tuple[list[str], str | None]:
    """Critério 7: `results` = erro de cada uma das 31 chamadas (`None` se deu certo).

    Devolve os problemas e o `request_id` da 31ª, para procurar na history.
    """
    problems: list[str] = []
    if len(results) != 31:
        return [f"esperava 31 chamadas, vieram {len(results)}"], None
    accepted = [r for r in results[:30] if r is None]
    if len(accepted) != 30:
        problems.append(f"só {len(accepted)} das 30 primeiras chamadas passaram: {results[:30]}")
    last = results[30]
    if not last or not last.startswith("RATE_LIMITED"):
        return [*problems, f"a 31ª chamada deveria dar RATE_LIMITED: {last!r}"], None
    if "retry_after_s=" not in last:
        problems.append("RATE_LIMITED sem retry_after_s")
    rid = _UUID.search(last)
    if not rid:
        problems.append("RATE_LIMITED sem request_id")
        return problems, None
    return problems, rid.group(0)


def check_history(
    rows: Sequence[Sequence[str | None]],
    blocked_request_id: str | None,
    profile_user: str,
    mode: str,
    trace_users: Sequence[str],
) -> list[str]:
    """Critérios 7 e 9 sobre `(executed_by, statement_text)` da `system.query.history`."""
    problems: list[str] = []
    atlas = [(by, text or "") for by, text in rows if _COMMENT.search(text or "")]
    if not atlas:
        return ["nenhuma query com o comentário atlas-mcp na system.query.history"]
    if blocked_request_id and any(blocked_request_id in text for _, text in atlas):
        problems.append("a chamada RATE_LIMITED aparece na system.query.history (rodou query)")
    executors = {by for by, _ in atlas}
    if mode == "obo":
        if executors != {profile_user}:
            problems.append(f"executed_by deveria ser {profile_user}: {sorted(executors, key=str)}")
    else:
        if profile_user in executors:
            problems.append("plano B: executed_by deveria ser o service principal, não o usuário")
        if set(trace_users) != {profile_user}:
            problems.append(f"plano B: o user do trace deveria ser {profile_user}: {trace_users}")
    return problems


async def _calls(url: str, token: str, month: str) -> tuple[list[str | None], list[str | None]]:
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    one_each: dict[str, dict[str, Any]] = {
        "health": {},
        "list_metrics": {},
        "query_metric": {
            "view": "mv_recharges",
            "measures": ["gross_revenue"],
            "dimensions": ["uf"],
            "month_from": month,
            "month_to": month,
        },
        "top_regions": {"measure": "gross_revenue", "level": "uf", "month": month},
        "compare_months": {
            "measure": "gross_revenue",
            "month_a": month,
            "month_b": month,
            "level": "region",
        },
    }
    burst_args = one_each["query_metric"]
    first: list[str | None] = []
    burst: list[str | None] = []
    async with Client(url, auth=token) as client:
        for tool, args in one_each.items():
            try:
                await client.call_tool(tool, args)
                first.append(None)
            except ToolError as exc:
                first.append(f"{tool}: {exc}")
    # Janela nova: as 5 chamadas acima gastaram do limite; espera zerar para as 31 valerem.
    time.sleep(61)
    async with Client(url, auth=token) as client:
        for _ in range(31):
            try:
                await client.call_tool("query_metric", burst_args)
                burst.append(None)
            except ToolError as exc:
                burst.append(str(exc))
    return first, burst


def _sql(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    command = ["databricks", "--profile", profile, "api", "post", "/api/2.0/sql/statements"]
    command += ["--json", json.dumps(body), "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    response = json.loads(result.stdout)
    if response.get("status", {}).get("state") != "SUCCEEDED":
        raise RuntimeError(str(response.get("status")))
    return list(response.get("result", {}).get("data_array", []))


HISTORY_SQL = (
    "SELECT executed_by, statement_text FROM system.query.history "
    "WHERE start_time > current_timestamp() - INTERVAL 30 MINUTES "
    "AND statement_text LIKE '/* atlas-mcp request_id=%'"
)


def _trace_spans(experiment_id: str, warehouse_id: str) -> list[dict[str, Any]]:
    import os

    import mlflow

    os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = warehouse_id
    since_ms = int((time.time() - 30 * 60) * 1000)
    traces = mlflow.search_traces(
        locations=[experiment_id],
        filter_string=f"trace.timestamp_ms > {since_ms}",
        max_results=200,
        return_type="list",
    )
    spans: list[dict[str, Any]] = []
    for trace in traces:
        for span in trace.data.spans:
            if span.parent_id is None:
                spans.append(
                    {
                        "attributes": dict(span.attributes or {}),
                        "outputs": getattr(span, "outputs", None),
                    }
                )
    return spans


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--experiment-id", required=True, help="id do experiment atlas_mcp_traces")
    parser.add_argument("--month", default="2026-10")
    parser.add_argument("--mode", choices=("obo", "service-principal"), default="obo")
    args = parser.parse_args(argv)

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    app = w.apps.get(APP_NAME)
    state = app.app_status.state.value if app.app_status and app.app_status.state else None
    if state != "RUNNING" or not app.url:
        print(f"FALHA: {APP_NAME} em {state!r} (rode `bundle run atlas_mcp`)")
        return 1
    scheme, _, token = w.config.authenticate().get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        print("FALHA: o perfil não devolveu um cabeçalho Authorization Bearer")
        return 1
    profile_user = str(w.current_user.me().user_name)

    first, burst = asyncio.run(_calls(f"{app.url.rstrip('/')}/mcp", token, args.month))
    problems = [f"tool falhou: {e}" for e in first if e]
    rate_problems, blocked = check_rate_limit(burst)
    problems += rate_problems

    deadline = time.time() + HISTORY_WAIT_S
    rows: list[list[str | None]] = []
    while time.time() < deadline:
        rows = _sql(args.profile, args.warehouse_id, HISTORY_SQL)
        if len(rows) >= 30:  # 30 do burst (+ as da primeira rodada)
            break
        time.sleep(20)
    spans = _trace_spans(args.experiment_id, args.warehouse_id)
    problems += check_spans(spans)
    trace_users = sorted({str(s["attributes"].get("user")) for s in spans})
    problems += check_history(rows, blocked, profile_user, args.mode, trace_users)

    print(f"traces: {len(spans)}; queries na history: {len(rows)}; modo: {args.mode}")
    for problem in problems:
        print(f"FALHA: {problem}")
    if not problems:
        print("OK: P11.4 critérios 7 a 9 (rate limit, traces sem outputs, executed_by)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
