"""Confere `semantic.mv_recharges` contra o SQL direto no gold (SPEC-004 §8, task P7.2).

Critério 1 da SPEC-004 §8: `MEASURE(gross_revenue)` do mês M é igual, ao centavo, ao SQL de
referência direto em `gold.fct_recharges`. A view só existe no workspace, então o **mantenedor**
roda este script:

    uv run python scripts/check_mv_consistency.py --target dev --profile <perfil> \\
        --warehouse-id <id>

Só lê. Compara `gross_revenue` por mês e o total (linha `TOTAL`); sai com 0 se todos os meses
são iguais e com 1 se algum difere, falta de um dos lados ou a consulta falha. Detecta divergência
entre o YAML e o gold, não erro na definição de negócio. Se o warehouse estiver frio e a consulta
não terminar em 50 s, rode de novo.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml


def build_compare_query(catalog: str) -> str:
    """Por mês: `MEASURE(gross_revenue)` vs soma direta no gold; mais a linha TOTAL."""
    return f"""
WITH mv AS (
  SELECT CAST(recharge_month AS DATE) AS m, MEASURE(gross_revenue) AS v
  FROM {catalog}.semantic.mv_recharges GROUP BY recharge_month
), mv_total AS (
  SELECT MEASURE(gross_revenue) AS v FROM {catalog}.semantic.mv_recharges
), direct AS (
  SELECT CAST(DATE_TRUNC('MONTH', recharge_date) AS DATE) AS m, SUM(amount_brl) AS v
  FROM {catalog}.gold.fct_recharges WHERE status = 'approved' GROUP BY 1
), direct_total AS (
  SELECT SUM(amount_brl) AS v FROM {catalog}.gold.fct_recharges WHERE status = 'approved'
), per_month AS (
  SELECT 0 AS ord, CAST(COALESCE(mv.m, direct.m) AS STRING) AS m,
         CAST(mv.v AS STRING) AS mv_v, CAST(direct.v AS STRING) AS direct_v
  FROM mv FULL OUTER JOIN direct ON mv.m = direct.m
), total AS (
  SELECT 1 AS ord, 'TOTAL' AS m, CAST(mv_total.v AS STRING) AS mv_v,
         CAST(direct_total.v AS STRING) AS direct_v
  FROM mv_total CROSS JOIN direct_total
)
SELECT m, mv_v, direct_v FROM (
  SELECT * FROM per_month UNION ALL SELECT * FROM total
) ORDER BY ord, m
"""  # noqa: S608  (catálogo vem de CATALOGS, sem entrada livre)


def _equal(mv_value: str | None, direct_value: str | None) -> bool:
    if mv_value is None or direct_value is None:
        return False
    try:
        a, b = Decimal(mv_value), Decimal(direct_value)
        return a.is_finite() and b.is_finite() and a == b
    except InvalidOperation:
        return False


def compare_lines(rows: Sequence[Sequence[str | None]]) -> list[str]:
    """Uma linha por mês (e TOTAL): `ok` se iguais ao centavo, `FALHA` caso contrário."""
    months = [row for row in rows if row[0] != "TOTAL"]
    if not months:
        return ["FALHA nenhum mês na metric view nem no gold"]
    if not any(row[0] == "TOTAL" for row in rows):
        return ["FALHA linha TOTAL ausente"]
    return [
        f"{'ok   ' if _equal(mv_v, direct_v) else 'FALHA'} {m}: "
        f"metric view {mv_v} vs gold {direct_v}"
        for m, mv_v, direct_v in rows
    ]


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

    rows = _run(args.profile, args.warehouse_id, build_compare_query(CATALOGS[args.target]))
    lines = compare_lines(rows)
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
