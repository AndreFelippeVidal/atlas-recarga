"""Confere o `health` do App `atlas-mcp` no workspace (SPEC-006 §7, critério 1; task P11.1).

O App só existe no workspace, então o **mantenedor** roda isto depois do deploy:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_mcp -t dev --profile andrevidal
    uv run python scripts/check_mcp_health.py --profile andrevidal

Conecta como cliente MCP real (Streamable HTTP em `<url do App>/mcp`) com a credencial do perfil
escolhido; ela fica em memória e nunca é impressa. Sai com 0 se `health` volta `healthy`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import Any

APP_NAME = "atlas-mcp"


def bearer_token(headers: dict[str, str]) -> str:
    """Extrai o token do cabeçalho `Authorization` que o SDK monta (nunca é impresso)."""
    value = headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ValueError("o perfil não devolveu um cabeçalho Authorization Bearer")
    return token


def evaluate_health(payload: dict[str, Any]) -> list[str]:
    """Problemas da resposta do `health`; lista vazia se está de pé."""
    problems: list[str] = []
    if payload.get("status") != "healthy":
        problems.append(f"status = {payload.get('status')!r}, esperado 'healthy'")
    if not payload.get("version"):
        problems.append("sem version")
    if "warehouse" not in payload:
        problems.append("sem warehouse")
    return problems


async def _call_health(url: str, token: str) -> dict[str, Any]:
    from fastmcp import Client

    async with Client(url, auth=token) as client:
        result = await client.call_tool("health", {})
    data = result.data
    return dict(data) if isinstance(data, dict) else {}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="perfil do arquivo de configuração")
    args = parser.parse_args(argv)

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    app = w.apps.get(APP_NAME)
    state = app.app_status.state.value if app.app_status and app.app_status.state else None
    if state != "RUNNING" or not app.url:
        print(f"FALHA: {APP_NAME} em {state!r} (rode `bundle run atlas_mcp`)")
        return 1
    payload = asyncio.run(
        _call_health(f"{app.url.rstrip('/')}/mcp", bearer_token(w.config.authenticate()))
    )
    print(f"health: {payload}")
    problems = evaluate_health(payload)
    for problem in problems:
        print(f"FALHA: {problem}")
    if not problems:
        print("OK: SPEC-006 §7 critério 1 (health = healthy)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
