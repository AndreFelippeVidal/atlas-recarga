# ruff: noqa: S608
"""Spike P15.2: medidas com janela na `mv_recharges` na Free Edition (SPEC-004 §5).

O mantenedor roda isto no `dev` (a metric view e o warehouse só existem no workspace):

    uv run python scripts/spike_window_measures.py run --target dev --profile andrevidal \\
        --warehouse-id <id>
    uv run python scripts/spike_window_measures.py drop --target dev --profile andrevidal \\
        --warehouse-id <id>

Modos:
- `run`: cria `<catalog>.semantic.mv_recharges_window_spike` (tenta `version: 1.1` e, se a
  criação falhar, `version: 0.1`), consulta as medidas com janela e compara cada resultado com
  o SQL direto no gold. Imprime uma linha por item do spike (1 a 7) e sai com 1 se algum
  item de valor divergir. Os itens 1 e 3 a 7 vêm do resultado; o 2 e o 6 vêm das comparações
  agrupadas e filtradas.
- `drop`: apaga a view descartável.

Só cria a view do spike; não toca em `mv_recharges`. O texto do resultado vai para
`docs/spikes/P15.2-window-measures.md` (feito à mão pelo agente depois da execução).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
import time
from collections.abc import Sequence
from decimal import Decimal

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
VIEW = "mv_recharges_window_spike"
MONTHS = ("2025-11-01", "2026-01-01", "2026-10-01")  # 1º da série, janeiro e o último
GROUPS = {  # dimensão da metric view -> expressão no gold
    "recharge_month": None,
    "region": "mu.region",
    "uf": "mu.uf",
    "municipality_ibge_code": "mu.municipality_ibge_code",
}
FILTERS = {
    "none": ("TRUE", "TRUE"),
    "pos_type": ("p.pos_type = 'pharmacy'", "pos_type = 'pharmacy'"),
}
MOM_PLACES = Decimal("0.0001")
REPEATS = 3

_FORMAT_BRL = """    format:
      type: currency
      currency_code: BRL
      decimal_places:
        type: exact
        places: 2
"""
_FORMAT_PCT = """    format:
      type: percentage
      decimal_places:
        type: max
        places: 4
"""
_APPROVED = "SUM(source.amount_brl) FILTER (WHERE source.status = 'approved')"


def _measure(name: str, expr: str, windows: str, fmt: str, version: str) -> str:
    extra = f"    synonyms: [{name}]\n{fmt}" if version == "1.1" else ""
    comment = f"    comment: Medida do spike P15.2 ({name}).\n" if version == "1.1" else ""
    return f"  - name: {name}\n    expr: {expr}\n{comment}{extra}{windows}"


def _window(*entries: tuple[str, str]) -> str:
    body = "".join(
        f"      - order: {order}\n        range: {rng}\n        semiadditive: last\n"
        for order, rng in entries
    )
    return f"    window:\n{body}"


def build_yaml(catalog: str, version: str) -> str:
    """YAML do spike. `version` é `1.1` (com synonyms/format/comment) ou `0.1` (sem eles)."""
    if version not in {"1.1", "0.1"}:
        raise ValueError(f"version inválida: {version!r}")
    dims = [
        ("recharge_month", "DATE_TRUNC('MONTH', source.recharge_date)"),
        ("recharge_year", "YEAR(source.recharge_date)"),
        ("region", "dim_pos.dim_municipality.region"),
        ("uf", "dim_pos.dim_municipality.uf"),
        ("municipality_ibge_code", "dim_pos.dim_municipality.municipality_ibge_code"),
        ("pos_type", "dim_pos.pos_type"),
        ("distributor_name", "dim_pos.dim_distributor.distributor_name"),
    ]
    head = f"""version: {version}
source: {catalog}.gold.fct_recharges
joins:
  - name: dim_pos
    source: {catalog}.gold.dim_pos
    'on': source.pos_id = dim_pos.pos_id
    joins:
      - name: dim_municipality
        source: {catalog}.gold.dim_municipality
        'on': dim_pos.municipality_ibge_code = dim_municipality.municipality_ibge_code
      - name: dim_distributor
        source: {catalog}.gold.dim_distributor
        'on': dim_pos.distributor_id = dim_distributor.distributor_id
dimensions:
"""
    dim_text = "".join(f"  - name: {n}\n    expr: {e}\n" for n, e in dims)
    cur = _window(("recharge_month", "current"))
    measures = [
        _measure("gross_revenue", _APPROVED, "", _FORMAT_BRL, version),
        _measure("revenue_cur", _APPROVED, cur, _FORMAT_BRL, version),
        _measure(
            "revenue_prev",
            _APPROVED,
            _window(("recharge_month", "trailing 1 month")),
            _FORMAT_BRL,
            version,
        ),
        _measure(  # item 3: trailing 3 inclui o mês atual?
            "revenue_trailing3",
            _APPROVED,
            _window(("recharge_month", "trailing 3 month")),
            _FORMAT_BRL,
            version,
        ),
        _measure(  # item 3: trailing 2 + atual = janela de 3 meses?
            "revenue_trailing2",
            _APPROVED,
            _window(("recharge_month", "trailing 2 month")),
            _FORMAT_BRL,
            version,
        ),
        _measure(  # item 3: trailing exclui o atual, então 3 meses = trailing 2 + atual
            "revenue_t3m",
            "COALESCE(MEASURE(revenue_trailing2), 0) + COALESCE(MEASURE(revenue_cur), 0)",
            "",
            _FORMAT_BRL,
            version,
        ),
        _measure(  # item 4: YTD zera em janeiro? (ano `current`, mês `cumulative`)
            "revenue_ytd",
            _APPROVED,
            _window(("recharge_year", "current"), ("recharge_month", "cumulative")),
            _FORMAT_BRL,
            version,
        ),
        _measure(  # item 5: NULL sem mês anterior e com base zero
            "revenue_mom_change",
            "(MEASURE(revenue_cur) - MEASURE(revenue_prev)) / NULLIF(MEASURE(revenue_prev), 0)",
            "",
            _FORMAT_PCT,
            version,
        ),
    ]
    return head + dim_text + "measures:\n" + "".join(measures)


def build_create_ddl(catalog: str, version: str) -> str:
    return (
        f"CREATE OR REPLACE VIEW {catalog}.semantic.{VIEW}\n"
        f"WITH METRICS\nLANGUAGE YAML\nAS $$\n{build_yaml(catalog, version)}\n$$"
    )


def build_view_query(catalog: str, group: str, flt: str, month: str) -> str:
    """Consulta `MEASURE()` do mês `month`, agrupada por `group` (item 2) e filtrada (item 6)."""
    select_group = "" if group == "recharge_month" else f"{group}, "
    where = f"recharge_month = DATE'{month}'" + ("" if flt == "none" else f" AND {FILTERS[flt][1]}")
    return (
        f"SELECT {select_group}recharge_month, "
        "CAST(MEASURE(revenue_cur) AS STRING) AS cur, "
        "CAST(MEASURE(revenue_trailing2) AS STRING) AS t2, "
        "CAST(MEASURE(revenue_t3m) AS STRING) AS t3, "
        "CAST(MEASURE(revenue_ytd) AS STRING) AS ytd, "
        "CAST(MEASURE(revenue_mom_change) AS STRING) AS mom "
        f"FROM {catalog}.semantic.{VIEW} WHERE {where} GROUP BY ALL ORDER BY ALL"
    )


def build_gold_query(catalog: str, group: str, flt: str, month: str) -> str:
    """SQL de referência direto no gold: receita mensal por grupo e janelas por `RANGE`."""
    gexpr = GROUPS[group]
    select_group = "" if gexpr is None else f"{gexpr} AS {group}, "
    group_by = "1" if gexpr is None else "1, 2"
    part = "" if gexpr is None else f"PARTITION BY {group} "
    pkey = "" if gexpr is None else f"{group}, "
    return (
        f"WITH m AS (SELECT DATE_TRUNC('MONTH', f.recharge_date) AS recharge_month, "
        f"{select_group}"
        "SUM(f.amount_brl) FILTER (WHERE f.status = 'approved') AS rev "
        f"FROM {catalog}.gold.fct_recharges f "
        f"JOIN {catalog}.gold.dim_pos p ON f.pos_id = p.pos_id "
        f"JOIN {catalog}.gold.dim_municipality mu "
        "ON p.municipality_ibge_code = mu.municipality_ibge_code "
        f"WHERE {FILTERS[flt][0]} GROUP BY {group_by}), "
        "x AS (SELECT *, YEAR(recharge_month) * 12 + MONTH(recharge_month) AS idx FROM m) "
        f"SELECT {'' if gexpr is None else group + ', '}recharge_month, "
        "CAST(rev AS STRING) AS cur, "
        f"CAST(COALESCE(SUM(rev) OVER ({part}ORDER BY idx "
        "RANGE BETWEEN 2 PRECEDING AND CURRENT ROW), 0) AS STRING) AS t3, "
        f"CAST(SUM(rev) OVER (PARTITION BY {pkey}YEAR(recharge_month) ORDER BY idx) "
        "AS STRING) AS ytd, "
        f"CAST(CASE WHEN LAG(idx) OVER ({part}ORDER BY idx) = idx - 1 "
        f"THEN (rev - LAG(rev) OVER ({part}ORDER BY idx)) "
        f"/ NULLIF(LAG(rev) OVER ({part}ORDER BY idx), 0) END AS STRING) AS mom "
        f"FROM x QUALIFY recharge_month = DATE'{month}' ORDER BY ALL"
    )


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def compare_rows(
    view_rows: Sequence[Sequence[str | None]],
    gold_rows: Sequence[Sequence[str | None]],
    key_width: int,
) -> list[str]:
    """Diferenças entre a view e o gold (vazia = igual).

    Linha da view: chave(s), `cur`, `t2`, `t3`, `ytd`, `mom`. Linha do gold: chave(s), `cur`,
    `t3`, `ytd`, `mom`. `cur`, `t3` e `ytd` ao centavo; `mom` em 4 casas decimais.
    """
    gold = {tuple(r[:key_width]): r[key_width:] for r in gold_rows}
    problems: list[str] = []
    for row in view_rows:
        key = tuple(row[:key_width])
        cur, _t2, t3, ytd, mom = row[key_width:]
        expected = gold.pop(key, None)
        if expected is None:
            problems.append(f"{key}: linha só na view")
            continue
        g_cur, g_t3, g_ytd, g_mom = expected
        for name, got, want in (("cur", cur, g_cur), ("t3", t3, g_t3), ("ytd", ytd, g_ytd)):
            if _dec(got) != _dec(want):
                problems.append(f"{key}: {name} view={got} gold={want}")
        a, b = _dec(mom), _dec(g_mom)
        if (a is None) != (b is None) or (
            a is not None and b is not None and a.quantize(MOM_PLACES) != b.quantize(MOM_PLACES)
        ):
            problems.append(f"{key}: mom view={mom} gold={g_mom}")
    problems.extend(f"{key}: linha só no gold" for key in gold)
    return problems


def _run(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    command = [
        "databricks", "--profile", profile, "api", "post", "/api/2.0/sql/statements",
        "--json", json.dumps(body), "-o", "json",
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"consulta falhou: {result.stderr.strip()}")
    response = json.loads(result.stdout)
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(f"consulta não terminou: {status.get('error') or status}")
    return list(response.get("result", {}).get("data_array", []))


def _timed(profile: str, warehouse_id: str, statement: str) -> float:
    """Mediana em ms de `REPEATS` execuções."""
    samples = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        _run(profile, warehouse_id, statement)
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples)


def cmd_run(catalog: str, profile: str, warehouse_id: str) -> int:
    lines: list[str] = []
    failed = False

    created = None
    for version in ("1.1", "0.1"):
        try:
            _run(profile, warehouse_id, build_create_ddl(catalog, version))
            created = version
            lines.append(f"ok    item 1: janela aceita com version: {version}")
            break
        except RuntimeError as exc:
            lines.append(f"FALHA item 1: version: {version} recusada: {exc}")
    if created is None:
        print("\n".join(lines))
        return 1
    if created != "1.1":
        lines.append("aviso item 1: só `0.1` (sem synonyms/format/comment) criou a view")

    for group in GROUPS:
        key_width = 1 if group == "recharge_month" else 2  # (grupo, mês) ou só o mês
        for flt in FILTERS:
            for month in MONTHS:
                label = f"item 2/6: grupo={group} filtro={flt} mês={month}"
                try:
                    view = _run(profile, warehouse_id, build_view_query(catalog, group, flt, month))
                    gold = _run(profile, warehouse_id, build_gold_query(catalog, group, flt, month))
                except RuntimeError as exc:
                    failed = True
                    lines.append(f"FALHA {label}: {exc}")
                    continue
                problems = compare_rows(view, gold, key_width)
                if problems:
                    failed = True
                    lines.append(f"FALHA {label}: {len(problems)} diferenças")
                    lines.extend(f"      {p}" for p in problems[:5])
                else:
                    lines.append(f"ok    {label}: {len(view)} linhas iguais ao gold")

    plain = (
        f"SELECT uf, CAST(MEASURE(gross_revenue) AS STRING) FROM {catalog}.semantic.{VIEW} "
        "WHERE recharge_month = DATE'2026-10-01' GROUP BY uf"
    )
    windowed = (
        f"SELECT uf, CAST(MEASURE(revenue_trailing2) AS STRING) FROM {catalog}.semantic.{VIEW} "
        "WHERE recharge_month = DATE'2026-10-01' GROUP BY uf"
    )
    t_plain = _timed(profile, warehouse_id, plain)
    t_window = _timed(profile, warehouse_id, windowed)
    lines.append(f"item 7: sem janela {t_plain:.0f} ms, com janela {t_window:.0f} ms (mediana)")

    print("\n".join(lines))
    print("\nItens 3, 4 e 5: leia as linhas `cur`/`t2`/`t3`/`ytd`/`mom` conferidas acima;")
    print("  t3 = gold com janela de 3 meses incluindo o atual; t2 = `trailing 2 month`.")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("mode", choices=("run", "drop"))
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True)
    args = parser.parse_args(argv)
    catalog = CATALOGS[args.target]
    if args.mode == "drop":
        _run(args.profile, args.warehouse_id, f"DROP VIEW IF EXISTS {catalog}.semantic.{VIEW}")
        print(f"removida: {catalog}.semantic.{VIEW}")
        return 0
    return cmd_run(catalog, args.profile, args.warehouse_id)


if __name__ == "__main__":
    sys.exit(main())
