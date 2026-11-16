"""Confere `semantic.mv_commission` (SPEC-004 §4 e §8, critério 2, task P8.11).

A view só existe no workspace, então o **mantenedor** roda este script depois do deploy:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_semantic_deploy -t dev --profile andrevidal
    uv run python scripts/check_mv_commission.py --target dev --profile andrevidal \\
        --warehouse-id <id>

Só lê. Falha (saída 1) se algum lote da view não for `locked` (rascunho vazando) ou se
`MEASURE(commission_total)` por mês diferir, ao centavo, da soma direta de `locked_lines` dos
lotes `locked`.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml


def build_leak_query(catalog: str) -> str:
    """Lotes que aparecem na view mas não estão `locked` em `batches` (esperado: nenhum)."""
    return (
        "WITH in_view AS (SELECT batch_id, MEASURE(commission_total) AS total "  # noqa: S608
        f"FROM {catalog}.semantic.mv_commission GROUP BY batch_id) "
        "SELECT v.batch_id, b.status FROM in_view v "
        f"LEFT JOIN {catalog}.commission.batches b ON b.batch_id = v.batch_id "
        "WHERE b.status IS NULL OR b.status <> 'locked'"
    )


def build_compare_query(catalog: str) -> str:
    """Soma por mês: metric view x `locked_lines` direto (só lotes `locked`) e 'TOTAL'."""
    return (
        "WITH mv AS (SELECT CAST(reference_month AS STRING) AS m, "  # noqa: S608
        "CAST(MEASURE(commission_total) AS STRING) AS v "
        f"FROM {catalog}.semantic.mv_commission GROUP BY reference_month), "
        "direct AS (SELECT CAST(b.reference_month AS STRING) AS m, "
        "CAST(SUM(l.commission_brl) AS STRING) AS v "
        f"FROM {catalog}.commission.locked_lines l "
        f"JOIN {catalog}.commission.batches b ON b.batch_id = l.batch_id "
        "WHERE b.status = 'locked' GROUP BY b.reference_month) "
        "SELECT COALESCE(mv.m, direct.m), mv.v, direct.v "
        "FROM mv FULL OUTER JOIN direct ON mv.m = direct.m ORDER BY 1"
    )


def leak_lines(rows: Sequence[Sequence[str | None]]) -> list[str]:
    if not rows:
        return ["ok    nenhum lote fora de `locked` na view"]
    return [f"FALHA lote {batch} aparece na view com status {status}" for batch, status in rows]


def compare_lines(rows: Sequence[Sequence[str | None]]) -> list[str]:
    if not rows:
        return ["FALHA mv_commission não devolveu linhas (nenhum lote travado?)"]
    lines = []
    for month, mv_value, direct_value in rows:
        try:
            ok = (
                mv_value is not None
                and direct_value is not None
                and Decimal(mv_value) == Decimal(direct_value)
            )
        except InvalidOperation:
            ok = False
        lines.append(
            f"{'ok   ' if ok else 'FALHA'} {month}: view {mv_value} x locked_lines {direct_value}"
        )
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
    return list(response.get("result", {}).get("data_array", []))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    args = parser.parse_args(argv)

    catalog = CATALOGS[args.target]
    lines = leak_lines(_run(args.profile, args.warehouse_id, build_leak_query(catalog)))
    lines += compare_lines(_run(args.profile, args.warehouse_id, build_compare_query(catalog)))
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
