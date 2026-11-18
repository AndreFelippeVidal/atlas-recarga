"""Executor SQL do `atlas-mcp`: warehouse via `databricks-sql-connector`, como o usuário (OBO).

No App, o token do usuário chega em `x-forwarded-access-token` (SPEC-006 §2, S0.5). Fora do App
(dev local) cai na credencial padrão do SDK. Os valores vão como parâmetros nomeados nativos.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

TOKEN_HEADER = "x-forwarded-access-token"  # noqa: S105 - nome do cabeçalho, não é segredo


class MissingUserToken(RuntimeError):
    """Dentro do App sem o token do usuário (OBO desligado ou sem o escopo `sql`)."""


def user_token(headers: Mapping[str, str]) -> str | None:
    token = headers.get(TOKEN_HEADER)
    if token:
        return token
    if "DATABRICKS_APP_NAME" in os.environ:
        raise MissingUserToken("o App não recebeu o token do usuário (habilite OBO com escopo sql)")
    return None


def make_executor(headers: Mapping[str, str]) -> Any:
    """Devolve `executor(sql, params) -> (columns, rows)` ligado ao usuário da chamada."""
    token = user_token(headers)
    warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]
    host = os.environ["DATABRICKS_HOST"].removeprefix("https://").rstrip("/")

    def run(sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        from databricks import sql as dbsql

        if token:
            conn = dbsql.connect(
                server_hostname=host,
                http_path=f"/sql/1.0/warehouses/{warehouse_id}",
                access_token=token,
            )
        else:
            from databricks.sdk.core import Config

            cfg = Config()
            conn = dbsql.connect(
                server_hostname=host,
                http_path=f"/sql/1.0/warehouses/{warehouse_id}",
                credentials_provider=lambda: cfg.authenticate,
            )
        with conn, conn.cursor() as cursor:
            cursor.execute(sql, dict(params))
            columns = [c[0] for c in cursor.description or []]
            return columns, [list(r) for r in cursor.fetchall()]

    return run
