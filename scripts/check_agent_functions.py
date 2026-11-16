"""Confere as UC functions do agente contra a metric view (SPEC-005 §3, task P10.1).

Critério da P10.1: os retornos batem com as metric views e `measure` inválido gera erro. As
funções só existem no workspace, então o **mantenedor** roda este script depois do deploy e do job
`atlas_semantic_deploy` (que cria as views e depois as funções):

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_semantic_deploy -t dev --profile andrevidal
    uv run python scripts/check_agent_functions.py --target dev --profile andrevidal \\
        --warehouse-id <id> --month 2026-10-01 --previous-month 2026-09-01

Só lê. Para cada medida e cada nível compara `fn_metric_by_region` com `MEASURE()` direto na
`mv_recharges` (igual ao centavo); confere `fn_compare_months` contra a diferença das duas
consultas diretas; confere que `fn_list_metrics` lista as 7 medidas e as 10 dimensões; e que
medida e nível inválidos falham com `INVALID_MEASURE` e `INVALID_LEVEL`. Sai com 0 se tudo bate.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from decimal import Decimal

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
LEVEL_KEYS = {
    "region": "region",
    "uf": "uf",
    "municipality": "municipality_ibge_code",
    "ddd": "ddd",
}
N_DIMENSIONS = 10
_DATE = re.compile(r"^\d{4}-\d{2}-01$")
TOLERANCE = Decimal("0.000001")  # a função arredonda para DECIMAL(24, 6)


def direct_query(catalog: str, measure: str, level: str, month: str) -> str:
    key = LEVEL_KEYS[level]
    return (
        f"SELECT CAST({key} AS STRING), CAST(MEASURE({measure}) AS STRING) "
        f"FROM {catalog}.semantic.mv_recharges WHERE recharge_month = DATE'{month}' "
        f"GROUP BY {key} ORDER BY {key}"
    )


def function_query(catalog: str, measure: str, level: str, month: str) -> str:
    return (
        f"SELECT key, CAST(value AS STRING) FROM {catalog}.semantic.fn_metric_by_region("
        f"'{measure}', '{level}', DATE'{month}') ORDER BY key"
    )


def compare_query(catalog: str, measure: str, level: str, a: str, b: str) -> str:
    return (
        "SELECT key, CAST(value_a AS STRING), CAST(value_b AS STRING), "
        "CAST(abs_change AS STRING) "
        f"FROM {catalog}.semantic.fn_compare_months('{measure}', DATE'{a}', DATE'{b}', "
        f"'{level}') ORDER BY key"
    )


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _close(x: Decimal | None, y: Decimal | None) -> bool:
    if x is None or y is None:
        return x is y
    return abs(x - y) <= TOLERANCE


def compare_rows(
    expected: Sequence[Sequence[str | None]], actual: Sequence[Sequence[str | None]]
) -> str | None:
    """`None` se as duas listas `(chave, valor)` batem; senão o motivo."""
    if not expected:
        return "a consulta direta não devolveu linhas"
    exp = {str(k): _dec(v) for k, v in expected}
    act = {str(k): _dec(v) for k, v in actual}
    if exp.keys() != act.keys():
        return f"chaves diferentes: {sorted(exp.keys() ^ act.keys())[:5]}"
    bad = [k for k in exp if not _close(exp[k], act[k])]
    return f"{len(bad)} chaves divergem, ex.: {bad[:3]}" if bad else None


def compare_change(
    direct_a: Sequence[Sequence[str | None]],
    direct_b: Sequence[Sequence[str | None]],
    actual: Sequence[Sequence[str | None]],
) -> str | None:
    """`abs_change` da função = valor B menos valor A das consultas diretas."""
    a = {str(k): _dec(v) for k, v in direct_a}
    b = {str(k): _dec(v) for k, v in direct_b}
    got = {str(k): (_dec(va), _dec(vb), _dec(ch)) for k, va, vb, ch in actual}
    if got.keys() != a.keys() | b.keys():
        return "chaves diferentes das consultas diretas"
    for key, (va, vb, change) in got.items():
        if not (_close(va, a.get(key)) and _close(vb, b.get(key))):
            return f"valores do mês divergem em {key}"
        expected = None if va is None or vb is None else vb - va
        if expected is not None and not _close(change, expected):
            return f"abs_change diverge em {key}"
    return None


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
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(str(status.get("error", status)))
    return list(response.get("result", {}).get("data_array", []))


def _expect_error(profile: str, warehouse_id: str, statement: str, code: str) -> str:
    try:
        _run(profile, warehouse_id, statement)
    except RuntimeError as error:
        ok = code in str(error)
        return f"{'ok   ' if ok else 'FALHA'} erro esperado {code}: {str(error)[:120]}"
    return f"FALHA {code}: a chamada inválida não falhou"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    parser.add_argument("--month", required=True, help="primeiro dia do mês, AAAA-MM-01")
    parser.add_argument("--previous-month", required=True, help="mês anterior, AAAA-MM-01")
    args = parser.parse_args(argv)
    for value in (args.month, args.previous_month):
        if not _DATE.fullmatch(value):
            parser.error(f"mês inválido (use AAAA-MM-01): {value!r}")

    catalog, profile, wh = CATALOGS[args.target], args.profile, args.warehouse_id
    lines: list[str] = []

    listed = _run(profile, wh, f"SELECT kind, name FROM {catalog}.semantic.fn_list_metrics()")
    measures = sorted(n for k, n in listed if k == "measure")
    dims = [n for k, n in listed if k == "dimension"]
    lines.append(
        f"{'ok   ' if measures == sorted(MEASURES) and len(dims) == N_DIMENSIONS else 'FALHA'} "
        f"fn_list_metrics: {len(measures)} medidas, {len(dims)} dimensões"
    )

    for level in LEVEL_KEYS:
        for measure in MEASURES:
            expected = _run(profile, wh, direct_query(catalog, measure, level, args.month))
            actual = _run(profile, wh, function_query(catalog, measure, level, args.month))
            problem = compare_rows(expected, actual)
            lines.append(
                f"{'FALHA' if problem else 'ok   '} fn_metric_by_region {measure} por {level}: "
                f"{problem or f'{len(actual)} linhas iguais à metric view'}"
            )

    for level in ("region", "uf"):
        direct_a = _run(
            profile, wh, direct_query(catalog, "gross_revenue", level, args.previous_month)
        )
        direct_b = _run(profile, wh, direct_query(catalog, "gross_revenue", level, args.month))
        actual = _run(
            profile,
            wh,
            compare_query(catalog, "gross_revenue", level, args.previous_month, args.month),
        )
        problem = compare_change(direct_a, direct_b, actual)
        lines.append(
            f"{'FALHA' if problem else 'ok   '} fn_compare_months gross_revenue por {level}: "
            f"{problem or 'diferença igual à das consultas diretas'}"
        )

    fn = f"{catalog}.semantic.fn_metric_by_region"
    lines.append(
        _expect_error(
            profile,
            wh,
            f"SELECT * FROM {fn}('revenue; DROP', 'region', DATE'{args.month}')",
            "INVALID_MEASURE",
        )
    )
    lines.append(
        _expect_error(
            profile,
            wh,
            f"SELECT * FROM {fn}('gross_revenue', 'pos', DATE'{args.month}')",
            "INVALID_LEVEL",
        )
    )
    lines.append(
        _expect_error(
            profile,
            wh,
            f"SELECT * FROM {fn}('gross_revenue', 'bogus', DATE'1999-01-01')",
            "INVALID_LEVEL",
        )
    )
    lines.append(
        _expect_error(
            profile,
            wh,
            f"SELECT * FROM {fn}('bogus', 'region', DATE'1999-01-01')",
            "INVALID_MEASURE",
        )
    )
    lines.append(
        _expect_error(
            profile,
            wh,
            f"SELECT * FROM {fn}(NULL, 'region', DATE'{args.month}')",
            "INVALID_MEASURE",
        )
    )

    # filtro `uf`: o parâmetro tem o mesmo nome da dimensão; um `uf = uf` devolveria todas as UFs
    ufs = _run(profile, wh, f"SELECT uf FROM {catalog}.semantic.mv_recharges GROUP BY uf LIMIT 1")
    sample = ufs[0][0] if ufs else None
    if sample:
        direct = _run(
            profile,
            wh,
            f"SELECT CAST(MEASURE(gross_revenue) AS STRING) FROM {catalog}.semantic.mv_recharges "
            f"WHERE recharge_month = DATE'{args.month}' AND uf = '{sample}'",
        )
        got = _run(
            profile,
            wh,
            f"SELECT key, CAST(value AS STRING) FROM {fn}('gross_revenue', 'uf', "
            f"DATE'{args.month}', '{sample}')",
        )
        problem = compare_rows([[sample, direct[0][0]]], got) if direct else "sem dado no mês"
        lines.append(
            f"{'FALHA' if problem else 'ok   '} fn_metric_by_region com uf = {sample}: "
            f"{problem or 'só a UF pedida, valor igual à metric view'}"
        )

    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
