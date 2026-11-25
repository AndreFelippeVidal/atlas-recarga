"""Confere `/api/months`, `/api/kpis` e `/api/health` do `atlas-web` no `dev` (P12.2).

O mantenedor roda isto (o warehouse só existe no workspace):

    DATABRICKS_CONFIG_PROFILE=andrevidal ATLAS_CATALOG=atlas_dev \
    DATABRICKS_HOST=https://<workspace> DATABRICKS_WAREHOUSE_ID=<id> \
        uv run python scripts/check_web_kpis.py [--month 2026-10]

Sobe o app em processo (sem deploy; o App é da P12.8) e confere:
1. `/api/months` traz o mês pedido e vem em ordem decrescente;
2. `gross_revenue` e `recharge_count` de `/api/kpis` batem, ao centavo, com um SQL direto sobre
   `gold.fct_recharges` (independente da metric view);
3. `/api/kpis` pela 2ª vez vem do cache (sem nova consulta);
4. `delta_pct` é coerente com o mês anterior;
5. (P15.3) com `pos_type=pharmacy`, `gross_revenue` e `recharge_count` batem com o SQL direto no
   gold com o mesmo filtro, `/api/filters` lista `pharmacy` e `pos_type=foo` dá 400.
O valor de `gross_revenue` impresso deve ser o mesmo do card do AI/BI "Visão Comercial".
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from decimal import Decimal
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None, help="YYYY-MM (padrão: o mês mais recente da API)")
    month = parser.parse_args(argv).month

    from atlas_web.app import create_app
    from atlas_web.sql_client import make_executor
    from fastapi.testclient import TestClient

    catalog = os.environ["ATLAS_CATALOG"]
    real = make_executor()
    queries: list[str] = []

    def counting(sql: str, params: Mapping[str, Any]) -> tuple[list[str], list[list[Any]]]:
        queries.append(sql)
        return real(sql, params)

    client = TestClient(create_app(executor=counting))
    problems: list[str] = []

    months = client.get("/api/months").json()["months"]
    month = month or months[0]
    if month not in months or months != sorted(months, reverse=True):
        problems.append(f"/api/months não traz {month} em ordem decrescente: {months}")

    body = client.get("/api/kpis", params={"month": month}).json()
    n_before = len(queries)
    client.get("/api/kpis", params={"month": month})
    if len(queries) != n_before:
        problems.append("a 2ª chamada de /api/kpis não veio do cache")

    _, rows = real(
        f"SELECT SUM(amount_brl), COUNT(1) FROM {catalog}.gold.fct_recharges "  # noqa: S608
        "WHERE status = 'approved' AND date_trunc('MONTH', recharge_date) = :m",
        {"m": f"{month}-01"},
    )
    direct_revenue, direct_count = Decimal(str(rows[0][0])), Decimal(str(rows[0][1]))
    if Decimal(body["gross_revenue"]["value"]) != direct_revenue:
        problems.append(f"gross_revenue {body['gross_revenue']['value']} != gold {direct_revenue}")
    if Decimal(body["recharge_count"]["value"]) != direct_count:
        problems.append(f"recharge_count {body['recharge_count']['value']} != gold {direct_count}")

    rev = body["gross_revenue"]
    if rev["previous"] is not None:
        expected = (Decimal(rev["value"]) - Decimal(rev["previous"])) / Decimal(rev["previous"])
        if abs(Decimal(rev["delta_pct"]) - expected * 100) > Decimal("0.01"):
            problems.append(f"delta_pct incoerente: {rev}")

    filters = client.get("/api/filters").json()
    if "pharmacy" not in filters.get("pos_types", []):
        problems.append(f"/api/filters sem pharmacy: {filters}")
    cut = client.get("/api/kpis", params={"month": month, "pos_type": "pharmacy"}).json()
    _, rows = real(
        f"SELECT SUM(f.amount_brl), COUNT(1) FROM {catalog}.gold.fct_recharges f "  # noqa: S608
        f"JOIN {catalog}.gold.dim_pos p ON f.pos_id = p.pos_id "
        "WHERE f.status = 'approved' AND p.pos_type = 'pharmacy' "
        "AND date_trunc('MONTH', f.recharge_date) = :m",
        {"m": f"{month}-01"},
    )
    cut_revenue = Decimal(str(rows[0][0] or 0))
    cut_count = Decimal(str(rows[0][1] or 0))
    if Decimal(cut["gross_revenue"]["value"]) != cut_revenue:
        problems.append(f"pharmacy: gross_revenue {cut['gross_revenue']['value']} != {cut_revenue}")
    if Decimal(cut["recharge_count"]["value"]) != cut_count:
        problems.append(f"pharmacy: recharge_count {cut['recharge_count']['value']} != {cut_count}")
    bad = client.get("/api/kpis", params={"month": month, "pos_type": "foo"}).status_code
    if bad != 400:
        problems.append(f"pos_type=foo: esperado 400, veio {bad}")

    print(f"health: {client.get('/api/health').json()}")
    print(f"pharmacy {month}: gross_revenue {cut['gross_revenue']['value']} (gold {cut_revenue})")
    print(f"gross_revenue {month}: {rev['value']} (compare com o AI/BI)")
    for problem in problems:
        print(f"FALHA: {problem}")
    print("ok" if not problems else "FALHOU")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
