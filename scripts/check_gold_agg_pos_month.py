"""Confere `gold.agg_pos_month` contra `gold.fct_recharges` (SPEC-002 §3, task P6.6).

Critério da P6.6: a soma bate com `fct_recharges` por mês. O pipeline só roda no workspace,
então o **mantenedor** roda este script depois do deploy e do refresh:

    uv run python scripts/check_gold_agg_pos_month.py --target dev --profile andrevidal \\
        --warehouse-id <id>

Só lê. Por mês compara valor aprovado, aprovadas e estornadas; sai com 0 se tudo bate e com 1
se algum mês difere. Também falha se houver duplicata de (pos_id, recharge_month).
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from decimal import Decimal

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml


def build_compare_query(catalog: str) -> str:
    """Diferença por mês entre a fato e o agregado; o catálogo vem de `CATALOGS`."""
    return f"""
WITH f AS (
  SELECT recharge_month,
         SUM(CASE WHEN status = 'approved' THEN amount_brl ELSE 0 END) AS amount,
         SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved,
         SUM(CASE WHEN status = 'reversed' THEN 1 ELSE 0 END) AS reversed
  FROM {catalog}.gold.fct_recharges GROUP BY recharge_month
), a AS (
  SELECT recharge_month, SUM(approved_amount_brl) AS amount,
         SUM(approved_count) AS approved, SUM(reversed_count) AS reversed
  FROM {catalog}.gold.agg_pos_month GROUP BY recharge_month
)
SELECT CAST(COALESCE(f.recharge_month, a.recharge_month) AS STRING) AS m,
       CAST(f.amount AS STRING), CAST(a.amount AS STRING),
       CAST(f.approved AS STRING), CAST(a.approved AS STRING),
       CAST(f.reversed AS STRING), CAST(a.reversed AS STRING)
FROM f FULL OUTER JOIN a ON f.recharge_month = a.recharge_month
ORDER BY m
"""  # noqa: S608  (catálogo vem de CATALOGS, sem entrada livre)


def build_duplicates_query(catalog: str) -> str:
    return (
        "SELECT COUNT(*) FROM (SELECT pos_id, recharge_month "  # noqa: S608
        f"FROM {catalog}.gold.agg_pos_month GROUP BY 1, 2 HAVING COUNT(*) > 1)"
    )


def month_lines(rows: Sequence[Sequence[str | None]]) -> list[str]:
    """Uma linha por mês, `ok` ou `FALHA`; compara os três pares fato vs agregado."""
    if not rows:
        return ["FALHA nenhum mês em fct_recharges nem em agg_pos_month"]
    lines = []
    for m, f_amt, a_amt, f_app, a_app, f_rev, a_rev in rows:
        same = (
            f_amt is not None
            and a_amt is not None
            and Decimal(f_amt) == Decimal(a_amt)
            and f_app == a_app
            and f_rev == a_rev
        )
        lines.append(
            f"{'ok   ' if same else 'FALHA'} {m}: valor {f_amt} vs {a_amt} · "
            f"aprovadas {f_app} vs {a_app} · estornadas {f_rev} vs {a_rev}"
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
    return list(response["result"]["data_array"])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    args = parser.parse_args(argv)

    catalog = CATALOGS[args.target]
    lines = month_lines(_run(args.profile, args.warehouse_id, build_compare_query(catalog)))
    dups = int(_run(args.profile, args.warehouse_id, build_duplicates_query(catalog))[0][0] or 0)
    lines.append(f"{'ok   ' if dups == 0 else 'FALHA'} duplicatas (pos_id, mês): {dups}")
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
