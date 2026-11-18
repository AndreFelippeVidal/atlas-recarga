"""Confere `list_metrics` e `query_metric` do App `atlas-mcp` (SPEC-006 §7, critérios 3 e 4; P11.2).

O App só existe no workspace, então o **mantenedor** roda isto depois do deploy:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_mcp -t dev --profile andrevidal
    uv run python scripts/check_mcp_query.py --profile andrevidal [--month 2026-10]

Conecta como cliente MCP real com a credencial do perfil (em memória, nunca impressa) e confere:
1. `list_metrics` traz `mv_recharges` e `mv_commission`;
2. `query_metric` por UF soma o mesmo que a consulta sem dimensão (ao centavo);
3. uma medida fora da lista devolve `INVALID_ARGUMENT`;
4. um filtro com aspas e `;` não quebra e não casa com nada (0 linhas ou só nulos: foi vinculado,
   não concatenado).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

APP_NAME = "atlas-mcp"
INJECTION = "SP'; DROP TABLE x; --"


def bearer_token(headers: dict[str, str]) -> str:
    value = headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ValueError("o perfil não devolveu um cabeçalho Authorization Bearer")
    return token


def evaluate(
    listed: dict[str, Any],
    by_uf: dict[str, Any],
    total: dict[str, Any],
    invalid_error: str | None,
    injection: dict[str, Any],
) -> list[str]:
    """Problemas encontrados; lista vazia se os critérios 3 e 4 passam."""
    problems: list[str] = []
    if set(listed.get("views", {})) != {"mv_recharges", "mv_commission"}:
        problems.append("list_metrics não traz as duas views")
    rows = by_uf.get("rows", [])
    uf_sum = sum((Decimal(str(r[-1])) for r in rows), Decimal(0))
    total_rows = total.get("rows", [])
    total_value = Decimal(str(total_rows[0][-1])) if total_rows else None
    if not rows:
        problems.append("query_metric por UF devolveu 0 linhas")
    if total_value is None or uf_sum != total_value:
        problems.append(f"soma das UFs ({uf_sum}) difere do total ({total_value})")
    if not by_uf.get("sql_fingerprint") or not by_uf.get("source"):
        problems.append("resposta sem source ou sql_fingerprint")
    if not invalid_error or "INVALID_ARGUMENT" not in invalid_error:
        problems.append(f"medida inválida não deu INVALID_ARGUMENT: {invalid_error!r}")
    # Sem dimensões não há GROUP BY: a agregação sobre zero linhas devolve 1 linha com valor nulo.
    if any(value is not None for row in injection.get("rows", []) for value in row):
        problems.append("o filtro com aspas e ';' deveria casar com nada (0 linhas ou só nulos)")
    return problems


async def _run(url: str, token: str, month: str) -> list[str]:
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    base = {
        "view": "mv_recharges",
        "measures": ["gross_revenue"],
        "month_from": month,
        "month_to": month,
    }
    async with Client(url, auth=token) as client:
        listed = (await client.call_tool("list_metrics", {})).data
        by_uf = (
            await client.call_tool("query_metric", {**base, "dimensions": ["uf"], "limit": 100})
        ).data
        total = (await client.call_tool("query_metric", base)).data
        try:
            await client.call_tool("query_metric", {**base, "measures": ["DROP TABLE x"]})
            invalid_error = None
        except ToolError as exc:
            invalid_error = str(exc)
        injection = (
            await client.call_tool("query_metric", {**base, "filters": {"uf": INJECTION}})
        ).data
    print(f"por UF: {len(by_uf['rows'])} linhas; total: {total['rows']}")
    return evaluate(listed, by_uf, total, invalid_error, injection)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="perfil do arquivo de configuração")
    parser.add_argument("--month", default="2026-10", help="mês YYYY-MM (padrão: 2026-10)")
    args = parser.parse_args(argv)

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    app = w.apps.get(APP_NAME)
    state = app.app_status.state.value if app.app_status and app.app_status.state else None
    if state != "RUNNING" or not app.url:
        print(f"FALHA: {APP_NAME} em {state!r} (rode `bundle run atlas_mcp`)")
        return 1
    problems = asyncio.run(
        _run(f"{app.url.rstrip('/')}/mcp", bearer_token(w.config.authenticate()), args.month)
    )
    for problem in problems:
        print(f"FALHA: {problem}")
    if not problems:
        print("OK: SPEC-006 §7 critérios 3 e 4 (lista fechada e parâmetros vinculados)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
