"""Religa os 3 Apps do Atlas Recarga e espera os healthchecks (P13.1, ADR-0009).

A Free Edition para cada App 24 h depois de iniciado ou redeployado. Antes da demo, rode:

    make apps-start PROFILE=andrevidal
    # ou: uv run python scripts/apps_start.py --profile andrevidal

1. inicia, sem esperar um pelo outro, os Apps que não estão `RUNNING` (`agent-atlas`, `atlas-mcp`,
   `atlas-web`);
2. espera os 3 chegarem a `RUNNING` (até `--timeout` segundos);
3. chama o healthcheck de cada um, repetindo até o prazo, porque `RUNNING` vem um pouco antes de o
   servidor responder:
   - `atlas-web`: `GET /api/health` com `status = healthy` (SPEC-007 §3);
   - `atlas-mcp`: a tool MCP `health` com `status = healthy` (SPEC-006 §3);
   - `agent-atlas`: `GET /health` do servidor do agente, ou `GET /` (a chat UI) se o proxy não
     repassar o `/health`; basta um dos dois devolver 200 (SPEC-005 não define um healthcheck).

A credencial do perfil fica em memória e nunca é impressa. Sai com 0 se os 3 Apps estão de pé.
Não faz deploy: só liga o que já está implantado (se o App nunca foi implantado, use
`databricks bundle deploy`). Os nomes dos Apps são os mesmos em `dev` e `demo`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from check_mcp_health import bearer_token, evaluate_health

DEFAULT_TIMEOUT_S = 600.0
POLL_INTERVAL_S = 10.0
HTTP_TIMEOUT_S = 30.0

Sleep = Callable[[float], None]
Clock = Callable[[], float]


@dataclass(frozen=True)
class AppSpec:
    """Um App do bundle e como saber se ele responde."""

    name: str
    kind: str  # "agent", "mcp" ou "web"


# Ordem do ADR-0009: agente, MCP, web. Os nomes são os de `resources.apps.*.name` no databricks.yml.
APPS: tuple[AppSpec, ...] = (
    AppSpec("agent-atlas", "agent"),
    AppSpec("atlas-mcp", "mcp"),
    AppSpec("atlas-web", "web"),
)

AGENT_PATHS = ("/health", "/")


def combined_state(app_state: str | None, compute_state: str | None) -> str | None:
    """`RUNNING` só se o App roda **e** o compute está `ACTIVE`; senão, os dois estados juntos.

    O auto-stop para o compute, e o `app_status.state` sozinho pode não refletir isso.
    """
    if app_state == "RUNNING" and compute_state in (None, "ACTIVE"):
        return "RUNNING"
    return f"{app_state}/{compute_state}"


def wait_until_running(
    names: Sequence[str],
    get_state: Callable[[str], str | None],
    *,
    timeout_s: float,
    interval_s: float = POLL_INTERVAL_S,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> dict[str, str | None]:
    """Consulta o estado dos Apps até todos estarem `RUNNING` ou o prazo acabar.

    Devolve o último estado visto de cada um (o chamador separa quem não chegou lá).
    """
    deadline = clock() + timeout_s
    states: dict[str, str | None] = {name: None for name in names}
    while True:
        for name in names:
            if states[name] != "RUNNING":
                try:
                    states[name] = get_state(name)
                except Exception as exc:  # erro transitório de rede: tenta de novo no próximo ciclo
                    states[name] = f"erro ({type(exc).__name__})"
        if all(state == "RUNNING" for state in states.values()) or clock() >= deadline:
            return states
        sleep(interval_s)


def retry_check(
    check: Callable[[], list[str]],
    *,
    timeout_s: float,
    interval_s: float = POLL_INTERVAL_S,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> list[str]:
    """Repete o healthcheck até ele não achar problema ou o prazo acabar; devolve o último."""
    deadline = clock() + timeout_s
    while True:
        problems = check()
        if not problems or clock() >= deadline:
            return problems
        sleep(interval_s)


def check_web_health(get_json: Callable[[str], tuple[int, Any]]) -> list[str]:
    """`atlas-web`: `/api/health` com HTTP 200 e `status = healthy`."""
    status, body = get_json("/api/health")
    if status != 200:
        return [f"/api/health devolveu HTTP {status}"]
    got = body.get("status") if isinstance(body, dict) else None
    return [] if got == "healthy" else [f"/api/health com status = {got!r}, esperado 'healthy'"]


def check_agent_health(get_status: Callable[[str], int]) -> list[str]:
    """`agent-atlas`: basta um dos caminhos de `AGENT_PATHS` devolver HTTP 200."""
    seen: list[str] = []
    for path in AGENT_PATHS:
        status = get_status(path)
        if status == 200:
            return []
        seen.append(f"{path} = HTTP {status}")
    return ["nenhum caminho respondeu 200: " + ", ".join(seen)]


async def _call_mcp_health(url: str, token: str) -> dict[str, Any]:
    from fastmcp import Client

    async with Client(url, auth=token) as client:
        result = await client.call_tool("health", {})
    data = result.data
    return dict(data) if isinstance(data, dict) else {}


def check_mcp_health(call_health: Callable[[], dict[str, Any]]) -> list[str]:
    """`atlas-mcp`: a tool `health` com `status = healthy` (mesmas regras do `check_mcp_health`)."""
    return evaluate_health(call_health())


def build_check(
    kind: str,
    base: str,
    get_response: Callable[[str, str], Any],
    headers: Callable[[], dict[str, str]],
) -> Callable[[], list[str]]:
    """Monta o healthcheck do App de um `kind` (`web`, `agent` ou `mcp`) sobre a URL `base`."""
    if kind == "web":

        def get_json(path: str) -> tuple[int, Any]:
            resp = get_response(base, path)
            return resp.status_code, resp.json() if resp.status_code == 200 else None

        return lambda: check_web_health(get_json)
    if kind == "agent":
        return lambda: check_agent_health(lambda path: int(get_response(base, path).status_code))
    if kind == "mcp":
        return lambda: check_mcp_health(
            lambda: asyncio.run(_call_mcp_health(f"{base}/mcp", bearer_token(headers())))
        )
    raise ValueError(f"kind desconhecido: {kind!r}")


def _probe(label: str, run: Callable[[], list[str]]) -> list[str]:
    """Roda um healthcheck sem deixar uma falha de rede derrubar os outros Apps."""
    try:
        return run()
    except Exception as exc:
        return [f"{label}: {type(exc).__name__}: {exc}"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="perfil do arquivo de configuração")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="segundos para esperar cada etapa (RUNNING e healthchecks)",
    )
    args = parser.parse_args(argv)

    import requests
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)

    def state_of(name: str) -> str | None:
        app = w.apps.get(name)
        app_state = app.app_status.state.value if app.app_status and app.app_status.state else None
        compute = (
            app.compute_status.state.value
            if app.compute_status and app.compute_status.state
            else None
        )
        return combined_state(app_state, compute)

    failures: dict[str, list[str]] = {}

    # 1) iniciar: todos de uma vez, pois cada start leva minutos.
    for spec in APPS:
        try:
            state = state_of(spec.name)
            if state == "RUNNING":
                print(f"{spec.name}: já está RUNNING")
                continue
            print(f"{spec.name}: {state} -> iniciando")
            w.apps.start(spec.name)
        except Exception as exc:
            failures[spec.name] = [f"não iniciou: {type(exc).__name__}: {exc}"]

    # 2) esperar RUNNING.
    pending = [spec.name for spec in APPS if spec.name not in failures]
    states = wait_until_running(pending, state_of, timeout_s=args.timeout)
    for name, state in states.items():
        if state != "RUNNING":
            failures[name] = [f"estado {state!r} depois de {args.timeout:.0f}s, esperado RUNNING"]

    # 3) healthchecks dos que estão de pé. O token é pedido a cada chamada (pode renovar).
    urls = {spec.name: (w.apps.get(spec.name).url or "").rstrip("/") for spec in APPS}

    def headers() -> dict[str, str]:
        return dict(w.config.authenticate())

    def get_response(base: str, path: str) -> Any:
        return requests.get(base + path, headers=headers(), timeout=HTTP_TIMEOUT_S)

    for spec in APPS:
        if spec.name in failures:
            continue
        base = urls[spec.name]
        if not base:
            failures[spec.name] = ["o App está RUNNING mas sem URL"]
            continue
        check = build_check(spec.kind, base, get_response, headers)
        problems = retry_check(partial(_probe, spec.name, check), timeout_s=args.timeout)
        if problems:
            failures[spec.name] = problems

    for spec in APPS:
        if spec.name in failures:
            for problem in failures[spec.name]:
                print(f"FALHA {spec.name}: {problem}")
        else:
            print(f"ok    {spec.name}: RUNNING e saudável ({urls[spec.name]})")
    ok = not failures
    print("OK: os 3 Apps estão de pé" if ok else "FALHOU: veja o runbook de demo no README")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
