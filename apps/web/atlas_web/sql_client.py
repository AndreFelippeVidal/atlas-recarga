"""Executor SQL do `atlas-web`: warehouse com o service principal do App (SPEC-007 §2).

No App, `Config()` lê `DATABRICKS_CLIENT_ID/SECRET` injetados pela plataforma. Os valores vão
como parâmetros nomeados nativos.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

Executor = Callable[[str, Mapping[str, Any]], tuple[list[str], list[list[Any]]]]


def make_executor() -> Executor:
    warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]
    host = os.environ["DATABRICKS_HOST"].removeprefix("https://").rstrip("/")

    def execute(sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        from databricks import sql as dbsql
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

    return execute
