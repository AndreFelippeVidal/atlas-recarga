"""Confere que `semantic.mv_recharges` responde a `MEASURE()` (SPEC-004 §3, task P7.1).

Critério da P7.1: `SELECT MEASURE(gross_revenue)` funciona. A view só existe no workspace,
então o **mantenedor** roda este script depois do deploy e do job `atlas_semantic_deploy`:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_semantic_deploy -t dev --profile andrevidal
    uv run python scripts/check_mv_recharges.py --target dev --profile andrevidal \\
        --warehouse-id <id>

Só lê. Roda as 7 medidas no total e `gross_revenue` por região (uma dimensão de join aninhado);
sai com 0 se todas respondem com valor e com 1 se alguma vem vazia ou a consulta falha. A
consistência com o SQL direto no gold é a P7.2.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
MEASURES = (
    "gross_revenue",
    "recharge_count",
    "avg_ticket",
    "active_pos",
    "revenue_per_active_pos",
    "reversal_rate",
    "distinct_subscribers",
)


def build_totals_query(catalog: str) -> str:
    """Todas as medidas sem agrupamento; o catálogo vem de `CATALOGS`."""
    cols = ", ".join(f"CAST(MEASURE({m}) AS STRING) AS {m}" for m in MEASURES)
    return f"SELECT {cols} FROM {catalog}.semantic.mv_recharges"  # noqa: S608


def build_by_region_query(catalog: str) -> str:
    return (
        "SELECT region, CAST(MEASURE(gross_revenue) AS STRING) "  # noqa: S608
        f"FROM {catalog}.semantic.mv_recharges GROUP BY region ORDER BY region"
    )


def totals_lines(row: Sequence[str | None]) -> list[str]:
    """Uma linha por medida: `ok` se veio com valor, `FALHA` se nula."""
    return [
        f"{'ok   ' if value is not None else 'FALHA'} MEASURE({name}) = {value}"
        for name, value in zip(MEASURES, row, strict=True)
    ]


def region_lines(rows: Sequence[Sequence[str | None]]) -> list[str]:
    if not rows:
        return ["FALHA gross_revenue por região não devolveu linhas"]
    lines = []
    for region, value in rows:
        try:
            ok = value is not None and Decimal(value) >= 0
        except InvalidOperation:
            ok = False
        lines.append(f"{'ok   ' if ok else 'FALHA'} região {region}: gross_revenue {value}")
    return lines


def _run(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
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
    return list(response["result"]["data_array"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    args = parser.parse_args(argv)

    catalog = CATALOGS[args.target]
    totals = _run(args.profile, args.warehouse_id, build_totals_query(catalog))
    by_region = _run(args.profile, args.warehouse_id, build_by_region_query(catalog))
    lines = totals_lines(totals[0]) + region_lines(by_region)
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
