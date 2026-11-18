"""Confere `top_regions`, `compare_months` e os erros padronizados do `atlas-mcp` (P11.3).

O App só existe no workspace, então o **mantenedor** roda isto depois do deploy:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_mcp -t dev --profile andrevidal
    uv run python scripts/check_mcp_tools.py --profile andrevidal \
        [--month-a 2026-09] [--month-b 2026-10]

Conecta como cliente MCP real com a credencial do perfil (em memória, nunca impressa) e confere:
1. `top_regions` por UF devolve as 5 maiores, em ordem decrescente, e o 1º bate com o
   `query_metric` por UF (mesma medida, ao centavo);
2. `compare_months` por UF traz `delta_abs = value_b - value_a` em cada linha com os dois meses;
3. `compare_months` por município ou cabe em 500 linhas ou devolve `RESULT_TOO_LARGE`;
4. `level` fora da lista devolve `INVALID_ARGUMENT`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

APP_NAME = "atlas-mcp"
MEASURE = "gross_revenue"


def bearer_token(headers: dict[str, str]) -> str:
    value = headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ValueError("o perfil não devolveu um cabeçalho Authorization Bearer")
    return token


def evaluate(
    top: dict[str, Any],
    by_uf: dict[str, Any],
    compare: dict[str, Any],
    municipality: dict[str, Any] | str,
    invalid_error: str | None,
) -> list[str]:
    """Problemas encontrados; lista vazia se P11.3 passa."""
    problems: list[str] = []
    top_values = [Decimal(str(r[-1])) for r in top.get("rows", [])]
    if len(top_values) != 5 or top_values != sorted(top_values, reverse=True):
        problems.append(f"top_regions deveria ter 5 linhas em ordem decrescente: {top_values}")
    uf_values = [Decimal(str(r[-1])) for r in by_uf.get("rows", [])]
    if not uf_values or not top_values or top_values[0] != max(uf_values):
        problems.append("o 1º do top_regions difere do maior valor do query_metric por UF")
    if not top.get("source") or not top.get("sql_fingerprint"):
        problems.append("top_regions sem source ou sql_fingerprint")

    rows = compare.get("rows", [])
    if not rows:
        problems.append("compare_months por UF devolveu 0 linhas")
    for row in rows:
        _, a, b, delta_abs, _pct = row
        if (
            a is not None
            and b is not None
            and Decimal(str(b)) - Decimal(str(a)) != Decimal(str(delta_abs))
        ):
            problems.append(f"delta_abs errado em {row[0]}: {row}")
    if not compare.get("source") or not compare.get("sql_fingerprint"):
        problems.append("compare_months sem source ou sql_fingerprint")

    if isinstance(municipality, str):
        if "RESULT_TOO_LARGE" not in municipality:
            problems.append(f"erro inesperado no município: {municipality!r}")
    elif len(municipality.get("rows", [])) > 500:
        problems.append("compare_months por município passou de 500 linhas sem RESULT_TOO_LARGE")

    if not invalid_error or "INVALID_ARGUMENT" not in invalid_error:
        problems.append(f"level inválido não deu INVALID_ARGUMENT: {invalid_error!r}")
    return problems


async def _run(url: str, token: str, month_a: str, month_b: str) -> list[str]:
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    cmp_args = {"measure": MEASURE, "month_a": month_a, "month_b": month_b}
    async with Client(url, auth=token) as client:
        top = (
            await client.call_tool(
                "top_regions", {"measure": MEASURE, "level": "uf", "month": month_b, "n": 5}
            )
        ).data
        by_uf = (
            await client.call_tool(
                "query_metric",
                {
                    "view": "mv_recharges",
                    "measures": [MEASURE],
                    "dimensions": ["uf"],
                    "month_from": month_b,
                    "month_to": month_b,
                    "limit": 100,
                },
            )
        ).data
        compare = (await client.call_tool("compare_months", {**cmp_args, "level": "uf"})).data
        municipality: dict[str, Any] | str
        try:
            municipality = (
                await client.call_tool("compare_months", {**cmp_args, "level": "municipality"})
            ).data
        except ToolError as exc:
            municipality = str(exc)
        try:
            await client.call_tool("top_regions", {**cmp_args, "level": "pais", "month": month_b})
            invalid_error = None
        except ToolError as exc:
            invalid_error = str(exc)
    print(f"top: {top['rows'][:2]}; compare por UF: {len(compare['rows'])} linhas")
    print(f"município: {municipality if isinstance(municipality, str) else 'coube em 500 linhas'}")
    return evaluate(top, by_uf, compare, municipality, invalid_error)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="perfil do arquivo de configuração")
    parser.add_argument("--month-a", default="2026-09", help="mês base YYYY-MM")
    parser.add_argument("--month-b", default="2026-10", help="mês comparado YYYY-MM")
    args = parser.parse_args(argv)

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    app = w.apps.get(APP_NAME)
    state = app.app_status.state.value if app.app_status and app.app_status.state else None
    if state != "RUNNING" or not app.url:
        print(f"FALHA: {APP_NAME} em {state!r} (rode `bundle run atlas_mcp`)")
        return 1
    problems = asyncio.run(
        _run(
            f"{app.url.rstrip('/')}/mcp",
            bearer_token(w.config.authenticate()),
            args.month_a,
            args.month_b,
        )
    )
    for problem in problems:
        print(f"FALHA: {problem}")
    if not problems:
        print("OK: P11.3 (top_regions, compare_months e erros padronizados)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
