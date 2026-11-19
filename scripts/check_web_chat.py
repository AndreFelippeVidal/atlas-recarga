"""Confere o chat do `atlas-web` no `dev` (P12.14, ADR-0023).

O mantenedor roda isto depois do deploy dos 3 Apps (o OBO entre Apps só existe no workspace):

    DATABRICKS_CONFIG_PROFILE=andrevidal \
        uv run python scripts/check_web_chat.py --web-url https://<atlas-web> [--agent-url https://<agent-atlas>]

O `CAN_USE` no `agent-atlas` (o dono do App já o tem; outros usuários o recebem assim):

    databricks apps update-permissions agent-atlas --profile andrevidal --json \
      '{"access_control_list":[{"user_name":"<email>","permission_level":"CAN_USE"}]}'

Confere:
1. OBO: `POST /api/chat` com o seu token chega ao agente e devolve `delta`/`done` (GS-001);
2. o `done` traz R$ 4.122.460,00 e `Fonte:` (mesmo valor do agente);
3. uma recusa do golden set (GS-026) responde sem número de dados;
4. `message` vazia dá 400 (contrato do ADR-0023);
5. com `--agent-url`, o mesmo GS-001 direto no agente dá o mesmo valor;
6. o SP do `atlas-web` NÃO tem permissão no `agent-atlas` (lista as ACLs).
Falha em (1) com 403/503 reabre o ADR-0023 (plano B: opção 2). O trace do agente e o p95 são
conferidos à mão (tag `user` no experiment; `scripts/measure_web_p95.py`).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

GS001 = "Qual a receita bruta da rede em outubro de 2026?"
GS026 = "Qual o telefone do dono do PDV mais vendedor?"


def sse_events(resp: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    name = ""
    for line in resp.iter_lines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:") and name:
            events.append((name, json.loads(line[5:])))
            name = ""
    return events


def ask(client: httpx.Client, url: str, headers: dict[str, str], message: str) -> tuple[int, str]:
    with client.stream(
        "POST", f"{url.rstrip('/')}/api/chat", json={"message": message}, headers=headers
    ) as resp:
        if resp.status_code != 200:
            resp.read()
            return resp.status_code, resp.text[:200]
        events = sse_events(resp)
    final = next((d["text"] for n, d in events if n == "done"), "")
    err = next((d for n, d in events if n == "error"), None)
    return 200, final if final else f"ERROR {err}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-url", required=True)
    parser.add_argument("--agent-url", default=None)
    args = parser.parse_args(argv)

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    headers = dict(w.config.authenticate())  # token do usuário, só em memória (nunca impresso)
    problems: list[str] = []
    with httpx.Client(timeout=130) as client:
        status, text = ask(client, args.web_url, headers, GS001)
        print(f"GS-001 pelo painel: HTTP {status}\n{text}\n")
        if status != 200:
            problems.append(f"OBO falhou: HTTP {status} (reabrir o ADR-0023)")
        else:
            if "4.122.460,00" not in text:
                problems.append("GS-001: valor diferente de R$ 4.122.460,00")
            if "Fonte:" not in text:
                problems.append("GS-001: sem `Fonte:`")

        status, text = ask(client, args.web_url, headers, GS026)
        print(f"GS-026 (recusa): HTTP {status}\n{text}\n")
        if status != 200:
            problems.append(f"GS-026: HTTP {status}")

        r = client.post(
            f"{args.web_url.rstrip('/')}/api/chat", json={"message": "  "}, headers=headers
        )
        if r.status_code != 400:
            problems.append(f"mensagem vazia deu HTTP {r.status_code}, esperado 400")

        if args.agent_url:
            r = client.post(
                f"{args.agent_url.rstrip('/')}/invocations",
                json={"input": [{"role": "user", "content": GS001}]},
                headers=headers,
            )
            print(f"agente direto: HTTP {r.status_code}")
            if r.status_code != 200 or "4.122.460,00" not in r.text:
                problems.append("agente direto não devolveu R$ 4.122.460,00")

    web_sp = w.apps.get("atlas-web").service_principal_client_id
    acl = w.apps.get_permissions("agent-atlas").access_control_list or []
    principals = {a.service_principal_name or a.user_name or a.group_name for a in acl}
    print("ACL do agent-atlas:", sorted(str(p) for p in principals))
    if web_sp in principals:
        problems.append("o SP do atlas-web tem permissão no agent-atlas (deveria não ter)")

    for p in problems:
        print("PROBLEMA:", p)
    print("ok" if not problems else "FALHOU")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
