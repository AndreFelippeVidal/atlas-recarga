"""Servidor FastMCP do Atlas (SPEC-006 §2): Streamable HTTP em /mcp."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from atlas_mcp.catalog import list_metrics as build_list_metrics
from atlas_mcp.health import health as build_health
from atlas_mcp.query import DEFAULT_LIMIT, InvalidArgument
from atlas_mcp.query import query_metric as run_query_metric
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
    headers = get_http_headers()

    def executor(sql: str, params: Any) -> Any:
        # Só abre conexão depois da validação: argumento inválido nunca chega ao warehouse.
        return make_executor(headers)(sql, params)

    try:
        return run_query_metric(
            os.environ.get("ATLAS_CATALOG", "atlas"),
            executor,
            view,
            measures,
            dimensions,
            filters,
            month_from,
            month_to,
            order_by,
            limit,
        )
    except InvalidArgument as exc:
        raise ToolError(f"INVALID_ARGUMENT: {exc}") from exc
    except MissingUserToken as exc:
        log.error("query_metric sem token do usuário")
        raise ToolError(
            "o App não recebeu o token do usuário; "
            "habilite a autorização on-behalf-of com o escopo sql"
        ) from exc
    except Exception as exc:  # o contrato completo de erros é da P11.3; aqui nada de stack trace
        # Só o tipo: o conector pode trazer detalhes de conexão (logs estruturados na P11.4).
        log.error("query_metric falhou: %s", type(exc).__name__)
        raise ToolError("falha ao executar a consulta; veja os logs do App") from exc


def main() -> None:
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")  # noqa: S104 - o App escuta atrás do proxy


if __name__ == "__main__":
    main()
