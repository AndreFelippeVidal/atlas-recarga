"""Confere o esqueleto do App `agent-atlas` no workspace (SPEC-005 §2 e §5, task P10.2).

Critério da P10.2: o agente responde "olá", o trace aparece no experiment e o uso aparece em
`system.ai_gateway.usage`. O App só existe no workspace, então o **mantenedor** roda isto depois
do deploy, de conceder ao service principal do App acesso ao model service
`system.ai.gpt-oss-120b` e de conversar com o agente pela chat UI do App ("olá"):

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run agent_atlas -t dev --profile andrevidal
    uv run python scripts/check_agent_skeleton.py --profile andrevidal \\
        --warehouse-id <id> --hours 3

Só lê: estado do App e linhas recentes da `usage` cujo `requester` é o service principal do App.
A `usage` atrasa de minutos a cerca de 1 hora (S0.2); repita se vier vazia. O trace no experiment
`/Shared/atlas/agent` (no `dev`, com o prefixo do usuário) e as tags `user`, `app_version`,
`prompt_version` e `llm_service` são conferidos na UI (aba Traces); o script lembra disso.
Sai com 0 se o App roda e há uso do LLM pelo gateway.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from typing import Any

APP_NAME = "agent-atlas"
# P10.5 (ADR-0021): o agente passou a usar o model service próprio
# `<catalog>.observability.agent_llm`
# (destino system.ai.gpt-oss-120b). O nome que a `usage` grava em `destination_name` não foi
# verificado, então aceitamos os dois.
EXPECTED_SERVICE = "system.ai.gpt-oss-120b"
EXPECTED_SERVICES = (EXPECTED_SERVICE, "agent_llm")
_UUID = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def evaluate_app(app: dict[str, Any]) -> list[str]:
    """Problemas do estado do App; lista vazia se está de pé."""
    problems: list[str] = []
    if app.get("name") != APP_NAME:
        problems.append(f"nome {app.get('name')!r}, esperado {APP_NAME!r}")
    state = (app.get("app_status") or {}).get("state")
    if state != "RUNNING":
        problems.append(f"app_status.state = {state!r}, esperado 'RUNNING'")
    if not app.get("service_principal_client_id"):
        problems.append("sem service_principal_client_id")
    return problems


def usage_query(requester: str, hours: int) -> str:
    if not _UUID.fullmatch(requester):
        raise ValueError(f"requester inválido: {requester!r}")
    if not 1 <= hours <= 72:
        raise ValueError("hours deve ficar entre 1 e 72")
    return (
        "SELECT CAST(event_time AS STRING), service_type, destination_name, "
        "CAST(status_code AS STRING), CAST(input_tokens AS STRING), "
        "CAST(output_tokens AS STRING) "
        "FROM system.ai_gateway.usage "
        f"WHERE requester = '{requester}' "
        f"AND event_time >= current_timestamp() - INTERVAL {hours} HOURS "
        "ORDER BY event_time DESC LIMIT 20"
    )


def evaluate_usage(rows: Sequence[Sequence[str | None]]) -> list[str]:
    """Problemas da `usage`: precisa ter chamada 200 ao model service esperado."""
    if not rows:
        return ["nenhuma linha na usage (o atraso chega a ~1 h; converse com o agente e repita)"]
    ok = [
        r
        for r in rows
        if r[1] == "MODEL_SERVICE"
        and any(name in (r[2] or "") for name in EXPECTED_SERVICES)
        and r[3] == "200"
    ]
    return (
        []
        if ok
        else [f"{len(rows)} linhas, mas nenhuma 200 em {EXPECTED_SERVICES} (MODEL_SERVICE)"]
    )


def _cli(profile: str, *args: str) -> Any:
    command = ["databricks", "--profile", profile, *args, "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def _sql(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    response = _cli(profile, "api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body))
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(str(status.get("error", status)))
    return list(response.get("result", {}).get("data_array", []))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que lê a usage")
    parser.add_argument("--hours", type=int, default=3, help="janela da usage (1 a 72 h)")
    args = parser.parse_args(argv)

    app = _cli(args.profile, "apps", "get", APP_NAME)
    app_problems = evaluate_app(app)
    print(f"{'FALHA' if app_problems else 'ok   '} App {APP_NAME}: {app_problems or 'RUNNING'}")
    if app_problems:
        return 1

    rows = _sql(
        args.profile, args.warehouse_id, usage_query(app["service_principal_client_id"], args.hours)
    )
    usage_problems = evaluate_usage(rows)
    print(
        f"{'FALHA' if usage_problems else 'ok   '} usage (últimas {args.hours} h): "
        f"{usage_problems or f'{len(rows)} linhas; a mais recente em {rows[0][0]}'}"
    )
    print(
        "manual: confira em Experiments > /Shared/atlas/agent (no dev, com o prefixo do usuário) "
        "um trace com as tags user, app_version, prompt_version e llm_service; confira também se "
        "a coluna request_tags da usage veio preenchida (rode o App com ATLAS_LLM_REQUEST_TAGS=1)."
    )
    return 1 if usage_problems else 0


if __name__ == "__main__":
    sys.exit(main())
