"""Confere os limites do LLM do agente no gateway (SPEC-005 §4 e §6, ADR-0021, task P10.5).

Critério da P10.5: 429 testado; política de PII ativa. O model service só existe no workspace,
então o **mantenedor** roda isto depois do deploy do bundle:

    databricks bundle deploy -t dev --profile andrevidal
    uv run python scripts/check_agent_guardrails.py --profile andrevidal \\
        --warehouse-id <id> --catalog atlas_dev

O que faz:
1. Lê o model service `<catalog>.observability.agent_llm` e confere destino, rate limit de
   30 req/min, freio de 500.000 tokens/hora e inference table.
2. Dispara uma rajada de chamadas de 1 token ao serviço (`--burst`, padrão 45, em paralelo) e
   exige pelo menos uma resposta 429. Gasta poucos tokens; roda como o usuário do perfil, e o
   limite `USER_DEFAULT` vale por requester. A CLI do Databricks refaz sozinha as chamadas com 429,
   então o 429 não aparece no retorno dela: ele é contado na inference table (`status_code = 429`
   desde o começo da rajada; o script espera até 3 min pelas linhas).
3. Lê a inference table `agent_llm_payload` (a linha pode atrasar alguns minutos).

A política de PII e a mensagem do 429 no agente são do App (`agent_server/guardrails.py`, testadas
no CI); a conferência manual está no `apps/agent/README.md`.
Sai com 0 se as 3 checagens passam.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

SERVICE_NAME = "agent_llm"
SCHEMA = "observability"
DESTINATION_MODEL = "models/system.ai.gpt-oss-120b"
REQUESTS_PER_MINUTE = 30
TOKENS_PER_HOUR = 500_000
_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


def evaluate_service(service: dict[str, Any]) -> list[str]:
    """Problemas na configuração do model service; lista vazia se bate com o ADR-0021."""
    problems: list[str] = []
    config = service.get("config") or {}
    destinations = (config.get("routing") or {}).get("destinations") or []
    models = [(d.get("pay_per_token_config") or {}).get("model") for d in destinations]
    if models != [DESTINATION_MODEL]:
        problems.append(f"destinos {models}, esperado [{DESTINATION_MODEL!r}]")
    limits = config.get("rate_limits") or []
    per_minute = [
        r
        for r in limits
        if r.get("key") == "RATE_LIMIT_KEY_USER_DEFAULT"
        and r.get("renewal_period") == "RATE_LIMIT_RENEWAL_PERIOD_MINUTE"
        and int(r.get("requests") or 0) == REQUESTS_PER_MINUTE
    ]
    if not per_minute:
        problems.append(f"falta o limite USER_DEFAULT de {REQUESTS_PER_MINUTE} req/min")
    per_hour = [
        r
        for r in limits
        if r.get("key") == "RATE_LIMIT_KEY_SERVICE"
        and r.get("renewal_period") == "RATE_LIMIT_RENEWAL_PERIOD_HOUR"
        and int(r.get("tokens") or 0) == TOKENS_PER_HOUR
    ]
    if not per_hour:
        problems.append(f"falta o limite SERVICE de {TOKENS_PER_HOUR} tokens/hora")
    if not (config.get("inference_table") or {}).get("parent"):
        problems.append("sem inference_table")
    return problems


def evaluate_burst(outcomes: Sequence[str], logged_429: int = 0) -> list[str]:
    """`outcomes` traz `ok`, `429` ou `erro: ...` por chamada; `logged_429` são os 429 que a
    inference table registrou na rajada. Precisa de ao menos um 429 em algum dos dois."""
    other = [o for o in outcomes if o not in ("ok", "429")]
    if other:
        return [f"{len(other)} chamadas falharam por outro motivo, ex.: {other[0]}"]
    if "429" not in outcomes and logged_429 < 1:
        return [
            f"nenhum 429 em {len(outcomes)} chamadas; o limite de {REQUESTS_PER_MINUTE}/min "
            "não vale"
        ]
    return []


def evaluate_payload_rows(rows: Sequence[Sequence[str | None]]) -> list[str]:
    n = int(rows[0][0] or 0) if rows else 0
    if n < 1:
        return ["a inference table está vazia (o atraso chega a alguns minutos; repita)"]
    return []


def burst_body(service: str) -> dict[str, Any]:
    return {"model": service, "messages": [{"role": "user", "content": "ok"}], "max_tokens": 1}


def classify(returncode: int, stderr: str) -> str:
    if returncode == 0:
        return "ok"
    if "429" in stderr or "RATE_LIMIT" in stderr.upper() or "REQUEST_LIMIT" in stderr.upper():
        return "429"
    return f"erro: {stderr.strip()[:120]}"


def _cli(profile: str, *args: str) -> Any:
    command = ["databricks", "--profile", profile, *args, "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def _call_once(profile: str, service: str) -> str:
    command = [
        "databricks",
        "--profile",
        profile,
        "api",
        "post",
        "/ai-gateway/mlflow/v1/chat/completions",
        "--json",
        json.dumps(burst_body(service)),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    return classify(result.returncode, result.stderr + result.stdout)


def _sql(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    response = _cli(profile, "api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body))
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(str(status.get("error", status)))
    return list(response.get("result", {}).get("data_array", []))


def burst_429_query(catalog: str, since_utc: str) -> str:
    if not _IDENT.fullmatch(catalog) or not re.fullmatch(
        r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", since_utc
    ):
        raise ValueError("catalog ou instante inválido")
    return (
        f"SELECT COUNT(*) FROM {catalog}.{SCHEMA}.{SERVICE_NAME}_payload "  # noqa: S608
        f"WHERE status_code = 429 AND event_time >= TIMESTAMP '{since_utc}'"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument(
        "--warehouse-id", required=True, help="SQL warehouse que lê a inference table"
    )
    parser.add_argument("--catalog", required=True, help="catálogo do target (atlas_dev no dev)")
    parser.add_argument("--burst", type=int, default=45, help="chamadas da rajada (> 30)")
    args = parser.parse_args(argv)
    if not _IDENT.fullmatch(args.catalog):
        parser.error("--catalog deve ser um identificador simples")
    if not REQUESTS_PER_MINUTE < args.burst <= 200:
        parser.error(f"--burst deve ficar entre {REQUESTS_PER_MINUTE + 1} e 200")

    service = f"{args.catalog}.{SCHEMA}.{SERVICE_NAME}"
    failed = False

    config = _cli(args.profile, "ai-gateway", "get-model-service", f"model-services/{service}")
    problems = evaluate_service(config)
    print(f"{'FALHA' if problems else 'ok   '} model service {service}: {problems or 'config ok'}")
    failed |= bool(problems)

    # 30 s de folga para o relógio local diferir do servidor
    started = (datetime.now(UTC) - timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S")
    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(lambda _: _call_once(args.profile, service), range(args.burst)))
    logged = 0
    for _ in range(18):  # a inference table atrasa; espera até ~3 min
        rows = _sql(args.profile, args.warehouse_id, burst_429_query(args.catalog, started))
        logged = int(rows[0][0] or 0) if rows else 0
        if logged:
            break
        time.sleep(10)
    problems = evaluate_burst(outcomes, logged)
    summary = (
        f"{outcomes.count('ok')} ok no retorno da CLI; {logged} respostas 429 na inference table"
    )
    print(f"{'FALHA' if problems else 'ok   '} rajada de {args.burst}: {problems or summary}")
    failed |= bool(problems)

    table = f"{args.catalog}.{SCHEMA}.{SERVICE_NAME}_payload"
    # catalog validado por regex; o resto é constante
    statement = f"SELECT COUNT(*) FROM {table}"  # noqa: S608
    rows = _sql(args.profile, args.warehouse_id, statement)
    problems = evaluate_payload_rows(rows)
    print(f"{'FALHA' if problems else 'ok   '} {table}: {problems or f'{rows[0][0]} linhas'}")
    failed |= bool(problems)

    print(
        'manual: no App, peça "qual a receita da rede em outubro? meu CPF é 123.456.789-09" e '
        "confira que a resposta não traz o CPF; depois mande mais de 30 mensagens em 1 minuto e "
        "confira a mensagem de limite e a tag error_type = rate_limited no trace."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
