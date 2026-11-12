"""Confere as contagens do bronze contra o `_manifest.json` (SPEC-002 §3, task P6.1).

Critério da P6.1: as contagens no bronze são iguais às do manifest. O pipeline só roda no
workspace, então o **mantenedor** roda este script depois do deploy e do refresh:

    uv run python scripts/check_bronze_counts.py --target dev --profile andrevidal

Só lê: um `SELECT count(*)` por tabela bronze. Sai com 0 se todas as contagens batem e com 1 se
alguma difere. `--manifest` aponta para o `_manifest.json` que foi enviado ao Volume.
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
# tabela bronze -> chave em `counts` do manifest (lista fechada: nenhum SQL livre)
BRONZE_TABLES = {
    "recharges": "recharges",
    "pos": "pos",
    "distributors": "distributors",
    "municipalities": "municipalities",
}
DEFAULT_MANIFEST = Path("data/generated/_manifest.json")


def expected_counts(manifest: Mapping[str, Any]) -> dict[str, int]:
    """Contagem esperada por tabela bronze, lida do manifest."""
    counts = manifest["counts"]
    missing = [key for key in BRONZE_TABLES.values() if key not in counts]
    if missing:
        raise KeyError(
            f"manifest sem contagem para: {', '.join(missing)} (rode `generate` de novo)"
        )
    return {table: int(counts[key]) for table, key in BRONZE_TABLES.items()}


def compare(expected: Mapping[str, int], actual: Mapping[str, int]) -> list[str]:
    """Uma linha por tabela, `ok` ou `FALHA`."""
    return [
        f"{'ok   ' if actual.get(table) == want else 'FALHA'} bronze.{table}: "
        f"manifest {want} · tabela {actual.get(table)}"
        for table, want in expected.items()
    ]


def build_query(catalog: str) -> str:
    """Um SELECT por tabela da lista fechada; o catálogo vem de `CATALOGS`."""
    parts = [
        # tabela e catálogo vêm de listas fechadas (BRONZE_TABLES, CATALOGS), sem entrada livre
        f"SELECT '{table}' AS t, count(*) AS n FROM {catalog}.bronze.{table}"  # noqa: S608
        for table in BRONZE_TABLES
    ]
    return " UNION ALL ".join(parts)


def _run(profile: str, warehouse_id: str, statement: str) -> dict[str, int]:
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
    return {row[0]: int(row[1]) for row in response["result"]["data_array"]}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    expected = expected_counts(manifest)
    actual = _run(args.profile, args.warehouse_id, build_query(CATALOGS[args.target]))
    lines = compare(expected, actual)
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
