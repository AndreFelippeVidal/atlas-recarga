"""Confere `/api/map/*` do `atlas-web` no `dev` (P12.3).

O mantenedor roda isto (o warehouse só existe no workspace):

    DATABRICKS_CONFIG_PROFILE=andrevidal ATLAS_CATALOG=atlas_dev \
    DATABRICKS_HOST=https://<workspace> DATABRICKS_WAREHOUSE_ID=<id> \
        uv run python scripts/check_web_map.py [--month 2026-10]

Sobe o app em processo e confere:
1. a soma das regiões e a das UFs de `gross_revenue` e `recharge_count` são iguais ao KPI;
2. a soma dos municípios de uma UF é igual à UF (medida aditiva);
3. `mom_change` responde nos 3 níveis e `measure=foo` / `region=XX` / `uf=XX` dão 400;
4. `avg_ticket` e `active_pos` respondem por região (valores vêm de `MEASURE()`, não de soma).
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None, help="YYYY-MM (padrão: o mês mais recente)")
    parser.add_argument("--uf", default="PA", help="UF para o nível município")
    args = parser.parse_args(argv)

    from atlas_web.app import create_app
    from fastapi.testclient import TestClient

    client = TestClient(create_app())
    problems: list[str] = []
    month = args.month or client.get("/api/months").json()["months"][0]
    base = {"month": month}

    def get(path: str, **params: str) -> list[dict[str, str | None]]:
        r = client.get(path, params={**base, **params})
        if r.status_code != 200:
            problems.append(f"{path} {params}: HTTP {r.status_code} {r.text[:120]}")
            return []
        body: list[dict[str, str | None]] = r.json()
        return body

    def total(items: list[dict[str, str | None]]) -> Decimal:
        return sum((Decimal(str(i["value"])) for i in items), Decimal(0))

    kpis = client.get("/api/kpis", params=base).json()
    for measure in ("gross_revenue", "recharge_count"):
        want = Decimal(kpis[measure]["value"])
        for path, level in (("/api/map/region", "regiões"), ("/api/map/uf", "UFs")):
            got = total(get(path, measure=measure))
            if got != want:
                problems.append(f"{measure}: soma das {level} {got} != KPI {want}")
        muns = total(get("/api/map/municipality", measure=measure, uf=args.uf))
        uf_value = next(
            (
                Decimal(str(i["value"]))
                for i in get("/api/map/uf", measure=measure)
                if i["uf"] == args.uf
            ),
            None,
        )
        if muns != uf_value:
            problems.append(f"{measure}: municípios de {args.uf} {muns} != UF {uf_value}")

    for path, extra in (
        ("/api/map/region", {}),
        ("/api/map/uf", {}),
        ("/api/map/municipality", {"uf": args.uf}),
    ):
        items = get(path, measure="mom_change", **extra)
        print(f"mom_change {path}: {len(items)} linhas; maior {items[:1]}")
    for measure in ("avg_ticket", "active_pos"):
        print(f"{measure} por região: {get('/api/map/region', measure=measure)}")

    bad = [
        ("/api/map/region", {"measure": "foo"}),
        ("/api/map/uf", {"measure": "gross_revenue", "region": "XX"}),
        ("/api/map/municipality", {"measure": "gross_revenue", "uf": "XX"}),
    ]
    for path, params in bad:
        status = client.get(path, params={**base, **params}).status_code
        if status != 400:
            problems.append(f"{path} {params}: esperado 400, veio {status}")

    for problem in problems:
        print(f"FALHA: {problem}")
    print("ok" if not problems else "FALHOU")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
