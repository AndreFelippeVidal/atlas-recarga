"""Aplica as UC functions do agente em `<catalog>.semantic` (SPEC-005 §3, task P10.1).

Roda como `spark_python_task` serverless no job `atlas_semantic_deploy` (databricks.yml), depois
das metric views. Idempotente: `CREATE OR REPLACE FUNCTION`.

* Medidas, dimensões e descrições vêm de `semantic/mv_recharges.yaml`: a definição é única
  (SPEC-004 §1). Nenhuma métrica é calculada aqui; as funções só chamam `MEASURE()`.
* **Sem SQL livre e sem SQL dinâmico:** `measure` e `level` são validados contra listas fechadas
  e escolhidos por `CASE` estático. Um valor fora da lista falha com `INVALID_MEASURE` ou
  `INVALID_LEVEL` (`raise_error`), mesmo que o mês não tenha linhas.
* Só `mv_recharges`: a comissão (`mv_commission`) fica fora do agente (SPEC-005 §3).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
SCHEMA = "semantic"
VIEW = "mv_recharges"

# nível -> (dimensão da chave, dimensão do rótulo); só dimensões que existem na metric view
LEVELS: dict[str, tuple[str, str]] = {
    "region": ("region", "region"),
    "uf": ("uf", "uf"),
    "municipality": ("municipality_ibge_code", "municipality_name"),
    "ddd": ("ddd", "ddd"),
}
GUARD_KEY = "__guard__"  # chave da linha sentinela que força a validação (nunca sai da função)
VALUE_TYPE = "DECIMAL(24, 6)"  # nunca DOUBLE/FLOAT (tech-stack, Proibido)

# Medidas com janela (SPEC-004 §5): fora das `fn_*` até a P15.6 definir a regra de consulta (só
# com `recharge_month`). As `aux_*` são pedaços de composição e nunca entram.
AUX_PREFIX = "aux_"
WINDOW_MEASURES_PENDING_P15_6 = frozenset(
    {"gross_revenue_t3m", "gross_revenue_ytd", "revenue_mom_change"}
)


def consumable(definition: dict[str, Any]) -> dict[str, Any]:
    """Cópia da definição sem as medidas auxiliares e sem as com janela (até a P15.6)."""
    kept = [
        m
        for m in definition["measures"]
        if not str(m["name"]).startswith(AUX_PREFIX)
        and m["name"] not in WINDOW_MEASURES_PENDING_P15_6
    ]
    return {**definition, "measures": kept}


def check_identifier(value: str, what: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def _lit(text: str) -> str:
    """Literal de string SQL de um texto do YAML do repo (aspas e `\\` escapados)."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _names(items: list[dict[str, Any]]) -> list[str]:
    return [check_identifier(i["name"], "metric view field") for i in items]


def _in_list(values: list[str]) -> str:
    return ", ".join(_lit(v) for v in values)


def build_list_metrics(catalog: str, definition: dict[str, Any]) -> str:
    """`fn_list_metrics()`: kind, name, description e synonyms de cada medida e dimensão."""
    check_identifier(catalog, "catalog name")
    rows = []
    for kind, key in (("measure", "measures"), ("dimension", "dimensions")):
        for field in definition[key]:
            name = check_identifier(field["name"], "metric view field")
            comment = " ".join(str(field["comment"]).split())
            synonyms = ", ".join(str(s) for s in field.get("synonyms", []))
            rows.append(f"    ({_lit(kind)}, {_lit(name)}, {_lit(comment)}, {_lit(synonyms)})")
    values = ",\n".join(rows)
    return (
        f"CREATE OR REPLACE FUNCTION {catalog}.{SCHEMA}.fn_list_metrics()\n"
        "RETURNS TABLE (kind STRING, name STRING, description STRING, synonyms STRING)\n"
        "COMMENT 'Lista as medidas e dimensões de mv_recharges com a descrição oficial. "
        "Somente leitura.'\n"
        "RETURN SELECT * FROM VALUES\n"
        f"{values}\n"
        "AS t(kind, name, description, synonyms)"
    )


def build_metric_by_region(catalog: str, definition: dict[str, Any]) -> str:
    """`fn_metric_by_region(measure, level, month, uf)`: uma medida por nível num mês."""
    check_identifier(catalog, "catalog name")
    measures = _names(definition["measures"])
    dimensions = set(_names(definition["dimensions"]))
    view = f"{catalog}.{SCHEMA}.{VIEW}"
    # Parâmetros sempre qualificados pelo nome da função: uma coluna com o mesmo nome (`uf`,
    # `level`) vence o parâmetro e o filtro viraria `uf = uf`.
    fq = "fn_metric_by_region"

    branches = []
    for level, (key, label) in LEVELS.items():
        if key not in dimensions or label not in dimensions:
            raise ValueError(f"nível {level!r}: dimensão ausente em {VIEW}")
        cols = ", ".join(f"MEASURE({m}) AS {m}" for m in measures)
        branches.append(
            f"    SELECT {_lit(level)} AS level, CAST({key} AS STRING) AS key,\n"
            f"           CAST({label} AS STRING) AS label, {cols}\n"
            f"    FROM {view}\n"
            f"    WHERE recharge_month = DATE_TRUNC('MONTH', {fq}.month)\n"
            f"      AND ({fq}.uf IS NULL OR uf = {fq}.uf)\n"
            f"    GROUP BY {', '.join(dict.fromkeys((key, label)))}"
        )
    union = "\n    UNION ALL\n".join(branches)
    # CAST por ramo: um CASE com tipos mistos promoveria tudo a DOUBLE antes do CAST final
    pick = "\n".join(f"        WHEN {_lit(m)} THEN CAST({m} AS {VALUE_TYPE})" for m in measures)
    # A guarda precisa ser avaliada mesmo sem linhas (mês vazio, nível inválido): um CROSS JOIN com
    # ela é podado quando o outro lado é vazio e o erro some. A linha sentinela abaixo sempre
    # existe e o filtro final a avalia (verificado no dev), então `raise_error` dispara sempre.
    guard = (
        "(SELECT CASE\n"
        f"        WHEN {fq}.measure IS NULL OR {fq}.measure NOT IN ({_in_list(measures)})\n"
        f"          THEN raise_error(CONCAT('INVALID_MEASURE: ', COALESCE({fq}.measure, 'NULL')))\n"
        f"        WHEN {fq}.level IS NULL OR {fq}.level NOT IN ({_in_list(list(LEVELS))})\n"
        f"          THEN raise_error(CONCAT('INVALID_LEVEL: ', COALESCE({fq}.level, 'NULL')))\n"
        "        ELSE 1 END AS ok)"
    )
    return (
        f"CREATE OR REPLACE FUNCTION {catalog}.{SCHEMA}.fn_metric_by_region(\n"
        "  measure STRING COMMENT 'Medida de mv_recharges (veja fn_list_metrics)',\n"
        "  level STRING COMMENT 'region, uf, municipality ou ddd',\n"
        "  month DATE COMMENT 'Qualquer dia do mês de negócio (America/Sao_Paulo)',\n"
        "  uf STRING DEFAULT NULL COMMENT 'Sigla da UF para filtrar; NULL para todas'\n"
        ")\n"
        f"RETURNS TABLE (level STRING, key STRING, label STRING, value {VALUE_TYPE})\n"
        "COMMENT 'Uma medida de mv_recharges por region, uf, municipality ou ddd num mês. "
        "Medida ou nível fora da lista falha com INVALID_MEASURE ou INVALID_LEVEL. "
        "Somente leitura.'\n"
        "RETURN\n"
        f"WITH guard AS {guard},\n"
        f"all_measures AS (\n{union}\n),\n"
        f"picked AS (\n  SELECT a.level, a.key, a.label, CASE {fq}.measure\n{pick}\n"
        "        END AS value\n"
        f"  FROM all_measures a WHERE a.level = {fq}.level\n)\n"
        "SELECT level, key, label, value FROM (\n"
        "  SELECT level, key, label, value FROM picked\n"
        "  UNION ALL\n"
        f"  SELECT CAST(NULL AS STRING), CASE WHEN ok = 1 THEN '{GUARD_KEY}' END,\n"
        f"         CAST(NULL AS STRING), CAST(NULL AS {VALUE_TYPE}) FROM guard\n"
        f") WHERE key IS DISTINCT FROM '{GUARD_KEY}'"
    )


def build_compare_months(catalog: str) -> str:
    """`fn_compare_months(...)`: variação absoluta e percentual, sobre `fn_metric_by_region`."""
    check_identifier(catalog, "catalog name")
    fn = f"{catalog}.{SCHEMA}.fn_metric_by_region"
    fc = "fn_compare_months"
    return (
        f"CREATE OR REPLACE FUNCTION {catalog}.{SCHEMA}.fn_compare_months(\n"
        "  measure STRING COMMENT 'Medida de mv_recharges (veja fn_list_metrics)',\n"
        "  month_a DATE COMMENT 'Mês base (qualquer dia do mês)',\n"
        "  month_b DATE COMMENT 'Mês comparado (qualquer dia do mês)',\n"
        "  level STRING COMMENT 'region, uf, municipality ou ddd',\n"
        "  uf STRING DEFAULT NULL COMMENT 'Sigla da UF para filtrar; NULL para todas'\n"
        ")\n"
        f"RETURNS TABLE (level STRING, key STRING, label STRING, value_a {VALUE_TYPE}, "
        f"value_b {VALUE_TYPE}, abs_change {VALUE_TYPE}, pct_change {VALUE_TYPE})\n"
        "COMMENT 'Variação do mês B contra o mês A de uma medida de mv_recharges: valor de "
        "cada mês, diferença absoluta e percentual (NULL quando o mês A é zero ou ausente). "
        "Somente leitura.'\n"
        "RETURN\n"
        "SELECT COALESCE(b.level, a.level) AS level, COALESCE(b.key, a.key) AS key,\n"
        "       COALESCE(b.label, a.label) AS label, a.value AS value_a, b.value AS value_b,\n"
        "       b.value - a.value AS abs_change,\n"
        "       CASE WHEN a.value IS NULL OR a.value = 0 THEN NULL\n"
        "            ELSE ROUND((b.value - a.value) / a.value * 100, 2) END AS pct_change\n"
        f"FROM {fn}({fc}.measure, {fc}.level, {fc}.month_a, {fc}.uf) a\n"
        f"FULL OUTER JOIN {fn}({fc}.measure, {fc}.level, {fc}.month_b, {fc}.uf) b\n"
        "  ON a.key <=> b.key"
    )


def build_all(catalog: str, definition: dict[str, Any]) -> list[tuple[str, str]]:
    """`(nome da função, DDL)` na ordem de criação (a terceira usa a segunda)."""
    definition = consumable(definition)
    return [
        ("fn_list_metrics", build_list_metrics(catalog, definition)),
        ("fn_metric_by_region", build_metric_by_region(catalog, definition)),
        ("fn_compare_months", build_compare_months(catalog)),
    ]


def main(catalog: str, directory: str) -> None:
    import yaml  # type: ignore[import-untyped]
    from pyspark.sql import SparkSession  # só existe no workspace

    check_identifier(catalog, "catalog name")
    definition = yaml.safe_load((Path(directory) / f"{VIEW}.yaml").read_text(encoding="utf-8"))
    spark: Any = SparkSession.builder.getOrCreate()
    for name, ddl in build_all(catalog, definition):
        spark.sql(ddl)
        print(f"aplicada: {catalog}.{SCHEMA}.{name}")


if __name__ == "__main__":
    # sem sys.exit: no serverless, `SystemExit` (até com 0) marca a task como falha
    main(sys.argv[1], sys.argv[2])
