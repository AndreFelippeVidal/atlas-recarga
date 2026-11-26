"""Confere as medidas com janela de `semantic.mv_recharges` contra o SQL direto no gold.

SPEC-004 §5 e §8 (task P15.5). Critérios: `gross_revenue_t3m` e `gross_revenue_ytd` iguais ao
centavo e `revenue_mom_change` igual em 4 casas, nos 12 meses, em 3 recortes (sem filtro,
`pos_type = 'pharmacy'` e um distribuidor). A view só existe no workspace, então o **mantenedor**
roda este script depois do deploy e do job `atlas_semantic_deploy`:

    uv run python scripts/check_mv_windows.py --target dev --profile <perfil> \\
        --warehouse-id <id> [--distributor "<nome>"]

Só lê. Sem `--distributor`, usa o distribuidor com mais receita aprovada. Por recorte:

* **mês a mês:** `GROUP BY recharge_month`, 12 linhas, contra o gold com `SUM() OVER` por `RANGE`
  sobre o índice do mês (janeiro e o primeiro mês da série incluídos);
* **forma dos consumidores:** `WHERE recharge_month = DATE'M'` (último mês) com `GROUP BY uf`,
  que tem de manter a janela (ADR-0025).

Regras do spike P15.2: `gross_revenue_t3m` vale 0,00 onde o gold dá `NULL` (soma de nada); o
`revenue_mom_change` é `NULL` no primeiro mês (sem mês anterior) e com base zero. Sai com 0 se
tudo bate e com 1 se algo difere, falta de um lado ou a consulta falha. Se o warehouse estiver
frio e a consulta não terminar em 50 s, rode de novo. Limite conhecido: um mês ou UF só com
recargas não aprovadas existe na metric view e não no gold (que filtra `approved`), e o script
acusa `FALHA`; os dados do `dev` não têm esse caso.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
POS_TYPE = "pharmacy"  # um dos 5 tipos de PDV (SPEC-001); recorte fixo
MONTHS = 12  # a série do dev vai de 2025-11 a 2026-10 (SPEC-001)
MOM_PLACES = Decimal("0.0001")  # critério da SPEC-004 §8: 4 casas


def sql_literal(value: str) -> str:
    """Literal de string SQL: só aspas simples e `\\` precisam de escape."""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _filters(
    pos_type: str | None, distributor: str | None, pos_prefix: str = "", dist_prefix: str = ""
) -> list[str]:
    parts = []
    if pos_type is not None:
        parts.append(f"{pos_prefix}pos_type = {sql_literal(pos_type)}")
    if distributor is not None:
        parts.append(f"{dist_prefix}distributor_name = {sql_literal(distributor)}")
    return parts


def mv_where(
    month: str | None = None, pos_type: str | None = None, distributor: str | None = None
) -> str:
    """`WHERE` na metric view: as dimensões são colunas diretas (sem alias)."""
    parts = _filters(pos_type, distributor)
    if month is not None:
        parts.insert(0, f"recharge_month = DATE'{month}'")
    return f"WHERE {' AND '.join(parts)}" if parts else ""


def gold_where(pos_type: str | None = None, distributor: str | None = None) -> str:
    parts = ["f.status = 'approved'", *_filters(pos_type, distributor, "p.", "d.")]
    return "WHERE " + " AND ".join(parts)


def build_top_distributor_query(catalog: str) -> str:
    return f"""
SELECT d.distributor_name, SUM(f.amount_brl) AS v
FROM {catalog}.gold.fct_recharges f
JOIN {catalog}.gold.dim_pos p ON f.pos_id = p.pos_id
JOIN {catalog}.gold.dim_distributor d ON p.distributor_id = d.distributor_id
WHERE f.status = 'approved'
GROUP BY d.distributor_name ORDER BY v DESC, d.distributor_name LIMIT 1
"""  # noqa: S608  (catálogo vem de CATALOGS, sem entrada livre)


_GOLD_JOINS = """
FROM {catalog}.gold.fct_recharges f
JOIN {catalog}.gold.dim_pos p ON f.pos_id = p.pos_id
JOIN {catalog}.gold.dim_distributor d ON p.distributor_id = d.distributor_id
JOIN {catalog}.gold.dim_municipality mu ON p.municipality_ibge_code = mu.municipality_ibge_code
"""

_GOLD_WINDOWS = """
  SUM(v) OVER (ORDER BY idx RANGE BETWEEN 2 PRECEDING AND CURRENT ROW) AS t3m,
  SUM(v) OVER (PARTITION BY yr ORDER BY idx
               RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ytd,
  SUM(v) OVER (ORDER BY idx RANGE BETWEEN 1 PRECEDING AND 1 PRECEDING) AS prev
"""


def build_monthly_query(
    catalog: str, pos_type: str | None = None, distributor: str | None = None
) -> str:
    """Por mês: as 3 medidas da metric view contra o gold. Colunas: m, 3 pares (mv, gold)."""
    where_mv = mv_where(None, pos_type, distributor)
    where_gold = gold_where(pos_type, distributor)
    joins = _GOLD_JOINS.format(catalog=catalog)
    return f"""
WITH mv AS (
  SELECT CAST(recharge_month AS DATE) AS m,
         MEASURE(gross_revenue_t3m) AS t3m, MEASURE(gross_revenue_ytd) AS ytd,
         MEASURE(revenue_mom_change) AS mom
  FROM {catalog}.semantic.mv_recharges {where_mv} GROUP BY recharge_month
), monthly AS (
  SELECT CAST(DATE_TRUNC('MONTH', f.recharge_date) AS DATE) AS m, SUM(f.amount_brl) AS v
  {joins} {where_gold} GROUP BY 1
), indexed AS (
  SELECT m, v, YEAR(m) AS yr, YEAR(m) * 12 + MONTH(m) AS idx FROM monthly
), direct AS (
  SELECT m, v, {_GOLD_WINDOWS} FROM indexed
)
SELECT CAST(COALESCE(mv.m, direct.m) AS STRING) AS m,
       CAST(mv.t3m AS STRING), CAST(direct.t3m AS STRING),
       CAST(mv.ytd AS STRING), CAST(direct.ytd AS STRING),
       CAST(mv.mom AS STRING),
       CAST((direct.v - direct.prev) / NULLIF(direct.prev, 0) AS STRING)
FROM mv FULL OUTER JOIN direct ON mv.m = direct.m
ORDER BY 1
"""  # noqa: S608  (catálogo vem de CATALOGS; filtros passam por sql_literal)


def build_uf_query(
    catalog: str, month: str, pos_type: str | None = None, distributor: str | None = None
) -> str:
    """Forma dos consumidores: mês filtrado e `GROUP BY uf`. Colunas: uf, 3 pares (mv, gold)."""
    where_mv = mv_where(month, pos_type, distributor)
    where_gold = gold_where(pos_type, distributor)
    joins = _GOLD_JOINS.format(catalog=catalog)
    return f"""
WITH mv AS (
  SELECT uf, MEASURE(gross_revenue_t3m) AS t3m, MEASURE(gross_revenue_ytd) AS ytd,
         MEASURE(revenue_mom_change) AS mom
  FROM {catalog}.semantic.mv_recharges {where_mv} GROUP BY uf
), monthly AS (
  SELECT mu.uf AS uf, CAST(DATE_TRUNC('MONTH', f.recharge_date) AS DATE) AS m,
         SUM(f.amount_brl) AS v
  {joins} {where_gold} GROUP BY 1, 2
), indexed AS (
  SELECT uf, m, v, YEAR(m) AS yr, YEAR(m) * 12 + MONTH(m) AS idx FROM monthly
), direct AS (
  SELECT uf, m, v,
    SUM(v) OVER (PARTITION BY uf ORDER BY idx RANGE BETWEEN 2 PRECEDING AND CURRENT ROW) AS t3m,
    SUM(v) OVER (PARTITION BY uf, yr ORDER BY idx
                 RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ytd,
    SUM(v) OVER (PARTITION BY uf ORDER BY idx RANGE BETWEEN 1 PRECEDING AND 1 PRECEDING) AS prev
  FROM indexed
)
SELECT COALESCE(mv.uf, direct.uf) AS uf,
       CAST(mv.t3m AS STRING), CAST(direct.t3m AS STRING),
       CAST(mv.ytd AS STRING), CAST(direct.ytd AS STRING),
       CAST(mv.mom AS STRING), CAST((direct.v - direct.prev) / NULLIF(direct.prev, 0) AS STRING)
FROM mv FULL OUTER JOIN (SELECT * FROM direct WHERE m = DATE'{month}') direct ON mv.uf = direct.uf
ORDER BY 1
"""  # noqa: S608  (catálogo vem de CATALOGS; mês e filtros passam por validação e sql_literal)


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"valor não numérico: {value!r}") from None
    if not parsed.is_finite():
        raise ValueError(f"valor não finito: {value!r}")
    return parsed


def money_equal(mv_value: str | None, gold_value: str | None) -> bool:
    """Ao centavo. O gold `NULL` vale 0 (o `t3m` soma nada, achado 2 do spike P15.2)."""
    try:
        a, b = _decimal(mv_value), _decimal(gold_value)
    except ValueError:
        return False
    if a is None:
        return False
    return a == (b if b is not None else Decimal(0))


def ytd_equal(mv_value: str | None, gold_value: str | None) -> bool:
    try:
        a, b = _decimal(mv_value), _decimal(gold_value)
    except ValueError:
        return False
    return a == b


def mom_equal(mv_value: str | None, gold_value: str | None) -> bool:
    """Em 4 casas; `NULL` só é igual a `NULL` (primeiro mês, base zero)."""
    try:
        a, b = _decimal(mv_value), _decimal(gold_value)
    except ValueError:
        return False
    if a is None or b is None:
        return a is None and b is None
    return a.quantize(MOM_PLACES, ROUND_HALF_EVEN) == b.quantize(MOM_PLACES, ROUND_HALF_EVEN)


def compare_lines(label: str, rows: Sequence[Sequence[str | None]]) -> list[str]:
    """Uma linha por chave (mês ou UF) e uma por medida que difere; `FALHA` se algo diverge."""
    if not rows:
        return [f"FALHA {label}: nenhuma linha na metric view nem no gold"]
    lines = []
    for key, mv_t3m, g_t3m, mv_ytd, g_ytd, mv_mom, g_mom in rows:
        bad = [
            name
            for name, ok in (
                ("t3m", money_equal(mv_t3m, g_t3m)),
                ("ytd", ytd_equal(mv_ytd, g_ytd)),
                ("mom", mom_equal(mv_mom, g_mom)),
            )
            if not ok
        ]
        detail = (
            f"t3m {mv_t3m}/{g_t3m} · ytd {mv_ytd}/{g_ytd} · mom {mv_mom}/{g_mom} (metric view/gold)"
        )
        status = f"FALHA ({', '.join(bad)})" if bad else "ok   "
        lines.append(f"{status} {label} {key}: {detail}")
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


def run_check(
    catalog: str, profile: str, warehouse_id: str, distributor: str | None = None
) -> list[str]:
    """Roda os 3 recortes (mês a mês e forma dos consumidores) e devolve as linhas do relatório."""
    if distributor is None:
        top = _run(profile, warehouse_id, build_top_distributor_query(catalog))
        if not top or not top[0][0]:
            return ["FALHA nenhum distribuidor com receita aprovada no gold"]
        distributor = str(top[0][0])
    recortes: list[tuple[str, str | None, str | None]] = [
        ("sem filtro", None, None),
        (f"pos_type={POS_TYPE}", POS_TYPE, None),
        (f"distribuidor={distributor}", None, distributor),
    ]
    lines: list[str] = []
    for label, pos_type, dist in recortes:
        monthly = _run(profile, warehouse_id, build_monthly_query(catalog, pos_type, dist))
        lines += compare_lines(f"[{label}] mês", monthly)
        if len(monthly) < MONTHS:
            lines.append(f"FALHA [{label}] mês: {len(monthly)} meses comparados, esperado {MONTHS}")
        if not monthly:
            continue
        last_month = str(monthly[-1][0])
        by_uf = _run(profile, warehouse_id, build_uf_query(catalog, last_month, pos_type, dist))
        lines += compare_lines(f"[{label}] UF em {last_month}", by_uf)
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    parser.add_argument("--distributor", help="nome do distribuidor (padrão: o de maior receita)")
    args = parser.parse_args(argv)

    lines = run_check(CATALOGS[args.target], args.profile, args.warehouse_id, args.distributor)
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
