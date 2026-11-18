"""Resposta da tool `health` (SPEC-006 §3), sem depender do FastMCP."""

from __future__ import annotations

import os
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from typing import Any

UNKNOWN = "UNKNOWN"
UNREACHABLE = "UNREACHABLE"
RETRY_TIMEOUT_S = 10


def app_version() -> str:
    try:
        return version("atlas-mcp")
    except PackageNotFoundError:  # rodando fora do pacote instalado
        return "0.0.0"


def warehouse_state(warehouse_id: str | None, fetch: Callable[[str], Any] | None = None) -> str:
    """Estado do SQL warehouse (RUNNING, STOPPED...). Nunca levanta: o health tem que responder."""
    if not warehouse_id:
        return UNKNOWN
    try:
        if fetch is None:
            from databricks.sdk import WorkspaceClient
            from databricks.sdk.core import Config

            # Sem isso o SDK repete 429/5xx por até 300 s e o health ficaria pendurado.
            fetch = WorkspaceClient(
                config=Config(retry_timeout_seconds=RETRY_TIMEOUT_S)
            ).warehouses.get
        state = fetch(warehouse_id).state
        return str(getattr(state, "value", state) or UNKNOWN)
    except Exception:  # qualquer falha vira UNREACHABLE, sem stack trace ao cliente
        return UNREACHABLE


def health(fetch: Callable[[str], Any] | None = None) -> dict[str, str]:
    """`status` diz que o servidor responde; `warehouse` informa o estado, sem derrubar o health."""
    return {
        "status": "healthy",
        "warehouse": warehouse_state(os.environ.get("DATABRICKS_WAREHOUSE_ID"), fetch),
        "version": app_version(),
    }
