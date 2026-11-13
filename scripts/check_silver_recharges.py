"""Confere `silver.recharges` contra o `_manifest.json` (SPEC-002 §5 critério 1, task P6.2).

Critério: `silver.recharges` = total gerado - duplicados - nulos - negativos, com diferença 0.
Os órfãos (`unknown_pos`) ainda **não** saem: a quarentena é da P6.3, então esta conferência os
mantém no esperado. O pipeline só roda no workspace, então o **mantenedor** roda depois do refresh:

    uv run python scripts/check_silver_recharges.py --target dev --profile andrevidal \\
        --warehouse-id <id>

Só lê: `SELECT` de contagens. Sai com 0 se bate e com 1 se difere.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
# cenários que reduzem o silver (lista fechada); `unknown_pos` só na P6.3
DROPPING_SCENARIOS = ("duplicates", "null_pos", "negative_amount")
DEFAULT_MANIFEST = Path("data/generated/_manifest.json")


def expected_silver_count(manifest: Mapping[str, Any]) -> int:
    """total gerado - duplicados - nulos - negativos (cenário ausente conta 0)."""
    scenarios = manifest.get("scenarios", {})
    dropped = sum(int(scenarios.get(name, {}).get("rows", 0)) for name in DROPPING_SCENARIOS)
    return int(manifest["counts"]["recharges"]) - dropped


def compare(expected: int, actual: int) -> str:
    status = "ok   " if expected == actual else "FALHA"
    diff = actual - expected
    return f"{status} silver.recharges: esperado {expected} · tabela {actual} · dif {diff}"


def build_query(catalog: str) -> str:
    """Contagem total e de `recharge_id` distintos; o catálogo vem de `CATALOGS`."""
    return (
        "SELECT count(*) AS n, count(DISTINCT recharge_id) AS d "  # noqa: S608
        f"FROM {catalog}.silver.recharges"
    )


def _run(profile: str, warehouse_id: str, statement: str) -> tuple[int, int]:
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
        raise RuntimeError(f"consulta falhou: {result.stderr.strip()}")
    response = json.loads(result.stdout)
    if response.get("status", {}).get("state") != "SUCCEEDED":
        raise RuntimeError(f"consulta não terminou: {response.get('status')}")
    row = response["result"]["data_array"][0]
    return int(row[0]), int(row[1])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    total, distinct = _run(args.profile, args.warehouse_id, build_query(CATALOGS[args.target]))
    lines = [
        compare(expected_silver_count(manifest), total),
        f"{'ok   ' if total == distinct else 'FALHA'} recharge_id único: {distinct} de {total}",
    ]
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
