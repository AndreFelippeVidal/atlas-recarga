"""Confere as permissões de `atlas_readers` (SPEC-004 §7 e §8, critério 4; task P7.3).

O **mantenedor** roda este script com o perfil da CLI de um usuário que está **só** em
`atlas_readers` (o segundo usuário do S0.6), depois de aplicar os grants:

    uv run python scripts/setup_workspace.py --target dev --profile andrevidal
    uv run python scripts/check_readers_permissions.py --target dev \\
        --profile <perfil-do-leitor> --warehouse-id <id>

Só lê. Espera `SELECT` em `semantic.mv_recharges` com sucesso e `PERMISSION_DENIED` em
`gold`, `silver`, `bronze` e `commission`. Sai com 0 se tudo bate e com 1 caso contrário.
`USE CATALOG` só deixa ver o catálogo; o `SELECT` em `semantic` não vaza os outros schemas.
O critério 4 fala do service principal do agente; ele só existe a partir da Fase 10, então aqui
o leitor é o segundo usuário do S0.6 (que não pode estar em outro grupo com acesso).
Um erro que não seja de permissão (tabela inexistente, warehouse parado) conta como FALHA:
só `PERMISSION_DENIED` prova o bloqueio.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
ALLOWED = (("semantic", "mv_recharges"),)
DENIED = (
    ("gold", "fct_recharges"),
    ("silver", "recharges"),
    ("bronze", "recharges"),
    ("commission", "locked_lines"),
)
DENIAL_MARKERS = ("permission_denied", "insufficient_permissions", "does not have select")


def build_select(catalog: str, schema: str, table: str) -> str:
    """`SELECT` de uma tabela de lista fechada; o catálogo vem de `CATALOGS`."""
    if schema == "semantic":
        return f"SELECT CAST(MEASURE(gross_revenue) AS STRING) FROM {catalog}.{schema}.{table}"  # noqa: S608
    return f"SELECT 1 FROM {catalog}.{schema}.{table} LIMIT 1"  # noqa: S608


def is_permission_denied(status: dict[str, object]) -> bool:
    """Só um estado FAILED com mensagem de permissão conta como bloqueio."""
    if status.get("state") != "FAILED":
        return False
    error = status.get("error")
    text = json.dumps(error).lower() if error else ""
    return any(marker in text for marker in DENIAL_MARKERS)


def _status(profile: str, warehouse_id: str, statement: str) -> dict[str, object]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    command = [
        "databricks",
        "--profile",
        profile,
        "api",
        "post",
        "/api/2.0/sql/statements",
        "--json",
        json.dumps(body),
        "-o",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"chamada falhou: {result.stderr.strip()}")
    status = json.loads(result.stdout).get("status", {})
    return dict(status) if isinstance(status, dict) else {}


def evaluate(
    allowed: dict[str, dict[str, object]], denied: dict[str, dict[str, object]]
) -> list[str]:
    lines = []
    for name, status in allowed.items():
        ok = status.get("state") == "SUCCEEDED"
        lines.append(
            f"{'ok   ' if ok else 'FALHA'} {name}: SELECT permitido ({status.get('state')})"
        )
    for name, status in denied.items():
        ok = is_permission_denied(status)
        detail = "PERMISSION_DENIED" if ok else str(status.get("state"))
        lines.append(f"{'ok   ' if ok else 'FALHA'} {name}: SELECT negado ({detail})")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil do leitor (só em atlas_readers)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    args = parser.parse_args(argv)

    catalog = CATALOGS[args.target]

    def probe(pairs: Sequence[tuple[str, str]]) -> dict[str, dict[str, object]]:
        return {
            f"{schema}.{table}": _status(
                args.profile, args.warehouse_id, build_select(catalog, schema, table)
            )
            for schema, table in pairs
        }

    lines = evaluate(probe(ALLOWED), probe(DENIED))
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
