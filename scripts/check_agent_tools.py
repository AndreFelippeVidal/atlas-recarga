"""Confere as tools do App `agent-atlas` no workspace (SPEC-005 §3 e §5, task P10.3).

Critério da P10.3: uma pergunta simples do golden set acerta. O App só existe no workspace, então
o **mantenedor** roda isto depois do deploy, com `ATLAS_LLM_REQUEST_TAGS=1` no App e de conversar
com o agente pela chat UI do App perguntando o caso GS-001
("Qual foi a receita de recarga da rede em outubro de 2026?"):

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run agent_atlas -t dev --profile andrevidal
    uv run python scripts/check_agent_tools.py --profile andrevidal \\
        --warehouse-id <id> --catalog atlas_dev --hours 3

Só lê. Confere (1) o App rodando; (2) o valor esperado do GS-001, calculado na metric view, para
você comparar com a resposta do agente; (3) a `request_tags` da `usage` do service principal do
App. O `ask_genie` (Genie Agent MCP) **não** aparece na `usage`: o endpoint não passa pelo Unity
Gateway (SPEC-005 §3). Os spans das tools (`ask_genie`, `fn_*`) são conferidos na UI (aba Traces
do experiment); o script lembra disso. A `usage` atrasa de minutos a cerca de 1 hora.
Sai com 0 se o App roda, o valor esperado existe e há linha de `usage` com `request_tags`.
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
_UUID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def evaluate_app(app: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if app.get("name") != APP_NAME:
        problems.append(f"nome {app.get('name')!r}, esperado {APP_NAME!r}")
    state = (app.get("app_status") or {}).get("state")
    if state != "RUNNING":
        problems.append(f"app_status.state = {state!r}, esperado 'RUNNING'")
    if not app.get("service_principal_client_id"):
        problems.append("sem service_principal_client_id")
    return problems


def expected_revenue_query(catalog: str) -> str:
    """O mesmo SQL da `reference_sql` do GS-001, com o catálogo do target."""
    if not _IDENTIFIER.fullmatch(catalog):
        raise ValueError(f"catálogo inválido: {catalog!r}")
    return (
        "SELECT CAST(MEASURE(gross_revenue) AS STRING) AS value "
        f"FROM {catalog}.semantic.mv_recharges "
        "WHERE recharge_month = DATE'2026-10-01'"
    )


def request_tags_query(requester: str, hours: int) -> str:
    if not _UUID.fullmatch(requester):
        raise ValueError(f"requester inválido: {requester!r}")
    if not 1 <= hours <= 72:
        raise ValueError("hours deve ficar entre 1 e 72")
    return (
        "SELECT CAST(event_time AS STRING), service_type, destination_name, "
        "CAST(request_tags AS STRING) "
        "FROM system.ai_gateway.usage "
        f"WHERE requester = '{requester}' "
        f"AND event_time >= current_timestamp() - INTERVAL {hours} HOURS "
        "ORDER BY event_time DESC LIMIT 20"
    )


def evaluate_expected(rows: Sequence[Sequence[str | None]]) -> list[str]:
    if len(rows) != 1 or rows[0][0] is None:
        return ["MEASURE(gross_revenue) de outubro/2026 não devolveu exatamente 1 valor"]
    return []


def evaluate_request_tags(rows: Sequence[Sequence[str | None]]) -> list[str]:
    """Precisa de uma chamada ao model service com `request_tags` preenchida."""
    if not rows:
        return ["nenhuma linha na usage (atraso de até ~1 h; converse com o agente e repita)"]
    tagged = [r for r in rows if r[1] == "MODEL_SERVICE" and r[3] not in (None, "", "{}", "null")]
    if tagged:
        return []
    return [
        f"{len(rows)} linhas, mas nenhuma com request_tags; confira ATLAS_LLM_REQUEST_TAGS=1 no "
        "App e, se o formato do extra_params for inválido, corrija ou remova o opt-in (SPEC-005 §5)"
    ]


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


def _report(label: str, problems: list[str], detail: str) -> None:
    print(f"{'FALHA' if problems else 'ok   '} {label}: {problems or detail}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda as queries")
    parser.add_argument("--catalog", required=True, help="catálogo do target (atlas_dev ou atlas)")
    parser.add_argument("--hours", type=int, default=3, help="janela da usage (1 a 72 h)")
    args = parser.parse_args(argv)

    app = _cli(args.profile, "apps", "get", APP_NAME)
    app_problems = evaluate_app(app)
    _report(f"App {APP_NAME}", app_problems, "RUNNING")
    if app_problems:
        return 1

    expected = _sql(args.profile, args.warehouse_id, expected_revenue_query(args.catalog))
    expected_problems = evaluate_expected(expected)
    _report("GS-001 esperado", expected_problems, f"gross_revenue de out/2026 = {expected[0][0]}")

    rows = _sql(
        args.profile,
        args.warehouse_id,
        request_tags_query(app["service_principal_client_id"], args.hours),
    )
    tag_problems = evaluate_request_tags(rows)
    _report(f"usage.request_tags (últimas {args.hours} h)", tag_problems, f"{len(rows)} linhas")

    print(
        "manual: pergunte o GS-001 no App e compare o número da resposta com o esperado acima "
        "(tolerância 0,5%); em Experiments > /Shared/atlas/agent (no dev, com o prefixo do "
        "usuário) confira no trace os spans TOOL `ask_genie` e `fn_*` (nome curto, sem catálogo). "
        "O ask_genie não aparece na usage: o Genie Agent MCP não passa pelo Unity Gateway."
    )
    return 1 if (expected_problems or tag_problems) else 0


if __name__ == "__main__":
    sys.exit(main())
