"""Spike P12.10: mede a latência do `atlas-web` e testa o agregado derivado da metric view.

O mantenedor roda isto no `dev` (o warehouse só existe no workspace). O app sobe em processo,
sem deploy (o App é da P12.8), então a rede entre o navegador e o App fica de fora da medida:

    DATABRICKS_CONFIG_PROFILE=andrevidal ATLAS_CATALOG=atlas_dev \
    DATABRICKS_HOST=https://<workspace> DATABRICKS_WAREHOUSE_ID=<id> \
        uv run python scripts/spike_dashboard_latency.py endpoints --label warehouse-frio

Modos:
- `endpoints`: cada endpoint com cache frio (1ª chamada) e cache quente (as seguintes), mais o
  tempo de aquecer tudo em sequência e em paralelo e o peso das geometrias. O estado do
  warehouse (parado ou aquecido) é decidido por quem roda: pare o warehouse antes do rótulo
  `warehouse-frio` e repita logo depois, com o `--label warehouse-quente`.
- `aggregate`: cria `<catalog>.semantic.spike_map_agg` por `MEASURE()` (agregado derivado da
  metric view, princípio 1) e mede a leitura dele contra a consulta direta à metric view.
- `drop`: remove a tabela do spike.
"""

from __future__ import annotations

import argparse
import gzip
import math
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

GEO_DIR = Path(__file__).resolve().parents[1] / "apps" / "web" / "public" / "geo"
AGG_TABLE = "spike_map_agg"
MEASURES = ("gross_revenue", "recharge_count", "avg_ticket", "active_pos")
CATALOG_RE = re.compile(r"[a-z][a-z0-9_]*")


def percentile(samples: Sequence[float], q: float) -> float:
    """Percentil por posto mais próximo (sem interpolação): honesto com poucas amostras."""
    if not samples:
        raise ValueError("sem amostras")
    ordered = sorted(samples)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def timed(call: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    result = call()
    return time.perf_counter() - start, result


def endpoint_plan(month: str, uf: str) -> list[tuple[str, str, dict[str, str]]]:
    """(rótulo, caminho, params) do que a tela chama em ordem de uso."""
    base = {"month": month}
    return [
        ("months", "/api/months", {}),
        ("kpis", "/api/kpis", base),
        ("map/region gross_revenue", "/api/map/region", {**base, "measure": "gross_revenue"}),
        ("map/uf gross_revenue", "/api/map/uf", {**base, "measure": "gross_revenue"}),
        ("map/region mom_change", "/api/map/region", {**base, "measure": "mom_change"}),
        (
            f"map/municipality {uf} gross_revenue",
            "/api/map/municipality",
            {**base, "measure": "gross_revenue", "uf": uf},
        ),
        (
            f"map/municipality {uf} mom_change",
            "/api/map/municipality",
            {**base, "measure": "mom_change", "uf": uf},
        ),
    ]


def format_row(label: str, samples: Sequence[float]) -> str:
    ms = [s * 1000 for s in samples]
    return (
        f"| {label} | {len(ms)} | {min(ms):.0f} | {percentile(ms, 50):.0f} "
        f"| {percentile(ms, 95):.0f} | {max(ms):.0f} |"
    )


def geometry_rows(uf: str) -> list[str]:
    rows = []
    for name in ("br-uf.json", f"mun/{uf}.json"):
        raw = (GEO_DIR / name).read_bytes()
        rows.append(
            f"| geo/{name} | {len(raw) / 1024:.0f} | {len(gzip.compress(raw)) / 1024:.0f} |"
        )
    return rows


def run_endpoints(args: argparse.Namespace) -> int:
    from atlas_web.app import create_app
    from fastapi.testclient import TestClient

    first = TestClient(create_app())
    month = args.month or first.get("/api/months").json()["months"][0]
    plan = endpoint_plan(month, args.uf)

    print(
        f"## Latência por endpoint — {args.label} (mês {month}, {args.repeat} chamadas quentes)\n"
    )
    print("| endpoint | n | mín ms | p50 ms | p95 ms | máx ms |")
    print("|---|---|---|---|---|---|")
    for label, path, params in plan:
        client = TestClient(create_app())  # cache novo: a 1ª chamada é fria
        cold, response = timed(partial(client.get, path, params=params))
        if response.status_code != 200:
            print(f"| {label} | HTTP {response.status_code} | | | | |")
            continue
        print(format_row(f"{label} (cache frio)", [cold]))
        hot = [timed(partial(client.get, path, params=params))[0] for _ in range(args.repeat)]
        print(format_row(f"{label} (cache quente)", hot))

    def warm(client: TestClient, item: tuple[str, str, dict[str, str]]) -> int:
        return int(client.get(item[1], params=item[2]).status_code)

    seq_client = TestClient(create_app())
    seq, _ = timed(lambda: [warm(seq_client, item) for item in plan])
    par_client = TestClient(create_app())
    with ThreadPoolExecutor(max_workers=4) as pool:
        par, _ = timed(lambda: list(pool.map(lambda item: warm(par_client, item), plan)))
    print("\n## Aquecer o cache na subida (todas as consultas da tela)\n")
    print("| modo | total ms |")
    print("|---|---|")
    print(f"| sequencial | {seq * 1000:.0f} |")
    print(f"| 4 em paralelo | {par * 1000:.0f} |")

    print("\n## Geometria (disco local; o tempo de rede vem da P12.8)\n")
    print("| arquivo | KB | KB gzip |")
    print("|---|---|---|")
    for row in geometry_rows(args.uf):
        print(row)
    return 0


# nível -> (colunas do GROUP BY além do mês, [região, uf, código, nome] ou NULL tipado)
_LEVELS: dict[str, tuple[str, tuple[str, str, str, str]]] = {
    "region": ("`region`", ("`region`", "NULL", "NULL", "NULL")),
    "uf": ("`region`, `uf`", ("`region`", "`uf`", "NULL", "NULL")),
    "municipality": (
        "`region`, `uf`, `municipality_ibge_code`, `municipality_name`",
        ("`region`", "`uf`", "`municipality_ibge_code`", "`municipality_name`"),
    ),
}


def _agg_sql(catalog: str) -> str:
    """Agregado por nível, só com `MEASURE()` da metric view: nada é somado fora dela."""
    view = f"{catalog}.semantic.mv_recharges"
    measures = ", ".join(f"MEASURE(`{m}`) AS `{m}`" for m in MEASURES)
    parts = []
    for level, (group, cols) in _LEVELS.items():
        region, uf, code, name = (c if c != "NULL" else "CAST(NULL AS STRING)" for c in cols)
        parts.append(
            f"SELECT '{level}' AS `level`, `recharge_month`, {region} AS `region`, "
            f"{uf} AS `uf`, {code} AS `municipality_ibge_code`, {name} AS `municipality_name`, "
            f"{measures} FROM {view} GROUP BY `recharge_month`, {group}"
        )
    return (
        f"CREATE OR REPLACE TABLE {catalog}.semantic.{AGG_TABLE} AS "
        "SELECT concat_ws('|', `level`, CAST(`recharge_month` AS STRING), "
        "coalesce(`region`, ''), coalesce(`uf`, ''), coalesce(`municipality_ibge_code`, '')) "
        f"AS `row_key`, * FROM ({' UNION ALL '.join(parts)})"
    )


def run_aggregate(args: argparse.Namespace, drop: bool) -> int:
    from atlas_web.sql_client import make_executor

    catalog = os.environ["ATLAS_CATALOG"]
    if not CATALOG_RE.fullmatch(catalog):
        print("ATLAS_CATALOG inválido")
        return 1
    execute = make_executor()
    table = f"{catalog}.semantic.{AGG_TABLE}"
    if drop:
        execute(f"DROP TABLE IF EXISTS {table}", {})
        print(f"removida: {table}")
        return 0

    build, _ = timed(lambda: execute(_agg_sql(catalog), {}))
    _, count = execute(f"SELECT COUNT(*) FROM {table}", {})
    print(f"criada: {table} ({count[0][0]} linhas) em {build:.1f}s")

    month = args.month or "2026-10"
    direct_sql = (
        f"SELECT `uf`, MEASURE(`gross_revenue`) AS `value` FROM {catalog}.semantic.mv_recharges "
        "WHERE `recharge_month` = :month GROUP BY ALL"
    )
    agg_sql = (
        f"SELECT `uf`, `gross_revenue` AS `value` FROM {table} "
        "WHERE `level` = 'uf' AND `recharge_month` = :month"
    )
    first = f"{month}-01"
    direct = [timed(lambda: execute(direct_sql, {"month": first}))[0] for _ in range(args.repeat)]
    agg = [timed(lambda: execute(agg_sql, {"month": first}))[0] for _ in range(args.repeat)]
    _, d_rows = execute(direct_sql, {"month": first})
    _, a_rows = execute(agg_sql, {"month": first})
    same = sorted((r[0], str(r[1])) for r in d_rows) == sorted((r[0], str(r[1])) for r in a_rows)
    print("\n| consulta | n | mín ms | p50 ms | p95 ms | máx ms |")
    print("|---|---|---|---|---|---|")
    print(format_row("UFs direto na metric view", direct))
    print(format_row("UFs no agregado", agg))
    print(f"\nvalores por UF iguais entre as duas: {'sim' if same else 'NÃO'}")
    return 0 if same else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("endpoints", "aggregate", "drop"))
    parser.add_argument("--label", default="warehouse-quente", help="rótulo da execução")
    parser.add_argument("--month", default=None, help="YYYY-MM (padrão: o mais recente)")
    parser.add_argument("--uf", default="SP", help="UF do nível município")
    parser.add_argument("--repeat", type=int, default=20, help="chamadas quentes por endpoint")
    args = parser.parse_args(argv)
    if args.mode == "endpoints":
        return run_endpoints(args)
    return run_aggregate(args, drop=args.mode == "drop")


if __name__ == "__main__":
    sys.exit(main())
