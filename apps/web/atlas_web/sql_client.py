"""Executor SQL do `atlas-web`: warehouse com o service principal do App (SPEC-007 §2).

No App, `Config()` lê `DATABRICKS_CLIENT_ID/SECRET` injetados pela plataforma. Os valores vão
como parâmetros nomeados nativos.

Abrir a conexão (auth + `dbsql.connect`) custava ~3 s por consulta; reaproveitá-la leva a consulta
a ~350 ms (ADR-0022). Há **uma conexão por thread**, aberta na 1ª consulta da thread. Se uma
conexão reaproveitada falha (expirou, o warehouse reiniciou), ela é fechada, reaberta e a consulta
é repetida **uma vez**; uma conexão recém-aberta que falha propaga o erro (o app responde 503).
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Any

log = logging.getLogger(__name__)

Executor = Callable[[str, Mapping[str, Any]], tuple[list[str], list[list[Any]]]]
Connect = Callable[[], Any]


class ConnectionExecutor:
    """Executa SQL numa conexão por thread, com uma reconexão em caso de erro."""

    def __init__(self, connect: Connect) -> None:
        self._connect = connect
        self._local = threading.local()

    def _close(self) -> None:
        conn = getattr(self._local, "conn", None)
        self._local.conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                log.debug("falha ao fechar a conexão", exc_info=True)

    @staticmethod
    def _run(conn: Any, sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        with conn.cursor() as cursor:
            cursor.execute(sql, dict(params))
            columns = [c[0] for c in cursor.description or []]
            return columns, [list(r) for r in cursor.fetchall()]

    def close_thread(self) -> None:
        """Fecha a conexão da thread atual (threads descartáveis, como as do aquecimento)."""
        self._close()

    def __call__(self, sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                return self._run(conn, sql, params)
            except Exception:
                log.warning("conexão reaproveitada falhou; reabrindo", exc_info=True)
                self._close()
        self._local.conn = self._connect()
        try:
            return self._run(self._local.conn, sql, params)
        except Exception:
            self._close()
            raise


def make_executor() -> Executor:
    warehouse_id = os.environ["DATABRICKS_WAREHOUSE_ID"]
    host = os.environ["DATABRICKS_HOST"].removeprefix("https://").rstrip("/")

    def connect() -> Any:
        from databricks import sql as dbsql
        from databricks.sdk.core import Config

        cfg = Config()
        return dbsql.connect(
            server_hostname=host,
            http_path=f"/sql/1.0/warehouses/{warehouse_id}",
            credentials_provider=lambda: cfg.authenticate,
        )

    return ConnectionExecutor(connect)
