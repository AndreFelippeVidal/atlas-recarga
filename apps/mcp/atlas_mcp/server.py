"""Servidor FastMCP do Atlas (SPEC-006 §2): Streamable HTTP em /mcp."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from atlas_mcp.catalog import list_metrics as build_list_metrics
from atlas_mcp.errors import McpError
from atlas_mcp.health import health as build_health
from atlas_mcp.query import DEFAULT_LIMIT
from atlas_mcp.query import query_metric as run_query_metric
from atlas_mcp.regions import DEFAULT_TOP_N
from atlas_mcp.regions import compare_months as run_compare_months
from atlas_mcp.regions import top_regions as run_top_regions
from atlas_mcp.sql_client import MissingUserToken, make_executor

log = logging.getLogger("atlas_mcp")

mcp = FastMCP("atlas-mcp")


@mcp.tool(annotations={"readOnlyHint": True})
def health() -> dict[str, str]:
    """Estado do servidor, do SQL warehouse e a versão do App."""
    return build_health()


@mcp.tool(annotations={"readOnlyHint": True})
def list_metrics() -> dict[str, Any]:
    """Medidas e dimensões de mv_recharges e mv_commission, com a descrição oficial."""
    return build_list_metrics()


@mcp.tool(annotations={"readOnlyHint": True})
def query_metric(
    view: str,
    measures: list[str],
    month_from: str,
    month_to: str,
    dimensions: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    order_by: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Consulta medidas de uma metric view (view, medidas e dimensões vêm de list_metrics).

    month_from/month_to: YYYY-MM, inclusivos. filters: dimensão -> valor ou lista de valores.
    order_by: coluna do resultado com asc/desc opcional. limit: 1 a 500.
    """
    return _run_tool(
        "query_metric",
        lambda catalog, executor: run_query_metric(
            catalog,
            executor,
            view,
            measures,
            dimensions,
            filters,
            month_from,
            month_to,
            order_by,
            limit,
        ),
    )


@mcp.tool(annotations={"readOnlyHint": True})
def top_regions(
    measure: str,
    level: str,
    month: str,
    n: int = DEFAULT_TOP_N,
    uf: str | None = None,
) -> dict[str, Any]:
    """Ranking de uma medida de mv_recharges por nível, em um mês (YYYY-MM).

    level: region, uf, municipality ou ddd. n: 1 a 50. uf: filtra por UF (opcional).
    """
    return _run_tool(
        "top_regions",
        lambda catalog, executor: run_top_regions(catalog, executor, measure, level, month, n, uf),
    )


@mcp.tool(annotations={"readOnlyHint": True})
def compare_months(
    measure: str,
    month_a: str,
    month_b: str,
    level: str,
    uf: str | None = None,
) -> dict[str, Any]:
    """Compara uma medida de mv_recharges entre dois meses (YYYY-MM), por nível.

    Devolve value_a, value_b, delta_abs (b - a) e delta_pct (nulo se a base é 0).
    Mais de 500 linhas: RESULT_TOO_LARGE (filtre por uf ou use um level mais agregado).
    """
    return _run_tool(
        "compare_months",
        lambda catalog, executor: run_compare_months(
            catalog, executor, measure, month_a, month_b, level, uf
        ),
    )


def _run_tool(name: str, call: Callable[[str, Any], dict[str, Any]]) -> dict[str, Any]:
    """Roda uma tool de consulta e traduz toda falha para o contrato do §4 (nunca stack trace)."""
    headers = get_http_headers()

    def executor(sql: str, params: Any) -> Any:
        # Só abre conexão depois da validação: argumento inválido nunca chega ao warehouse.
        return make_executor(headers)(sql, params)

    try:
        return call(os.environ.get("ATLAS_CATALOG", "atlas"), executor)
    except McpError as exc:
        raise ToolError(exc.render()) from exc
    except MissingUserToken as exc:
        log.error("%s sem token do usuário", name)
        raise ToolError(
            "o App não recebeu o token do usuário; "
            "habilite a autorização on-behalf-of com o escopo sql"
        ) from exc
    except Exception as exc:
        # Só o tipo: o conector pode trazer detalhes de conexão (logs estruturados na P11.4).
        log.error("%s falhou: %s", name, type(exc).__name__)
        raise ToolError("falha ao executar a consulta; veja os logs do App") from exc


def main() -> None:
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")  # noqa: S104 - o App escuta atrás do proxy


if __name__ == "__main__":
    main()
