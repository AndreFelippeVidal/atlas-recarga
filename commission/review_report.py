"""Relatório `commission_review` do lote de comissão (SPEC-003 §5.4, task P8.8).

As consultas ficam em `commission/review_sql/*.sql` (uma fonte só). Dois consumidores:

* o AI/BI Dashboard `semantic/dashboards/commission_review.lvdash.json`, **gerado** por
  `scripts/build_commission_review_dashboard.py` a partir destas consultas (um teste confere
  que o JSON versionado é igual ao gerado);
* o notebook `commission/commission_review.py`, que roda as mesmas consultas para um `batch_id`.

Somente leitura de `commission.*`. Nada aqui calcula, aprova ou grava: o relatório mostra o que o
job `atlas_commission_draft` gravou. Sem IA (ADR-0010).

Cada consulta devolve `batch_id` e **não** filtra: o dashboard filtra pelo campo (filtro global) e o
notebook embrulha a consulta com `WHERE batch_id = :batch_id`. Por isso nenhuma usa `LIMIT`
global: o corte do top 20 é por lote, com `row_number()`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SQL_DIR = Path(__file__).parent / "review_sql"
_BATCH_ID = re.compile(r"COM-\d{4}-\d{2}-(?:v\d+|ADJ-\d+)")
CATALOGS = frozenset({"atlas_dev", "atlas"})  # os catálogos do databricks.yml (dev, demo)

# O que cada flag significa (SPEC-003 §5.3). Só destaque para a revisão humana: nada é bloqueado.
FLAG_MEANING: dict[str, str] = {
    "spike_3x": "comissão do PDV maior que 3 vezes a média dos 3 meses anteriores",
    "fractioning_suspect": "mais de 20 recargas de R$ 10 do mesmo assinante em < 10 min",
    "tier_jump": "PDV subiu 2 ou mais faixas em relação ao mês anterior",
    "closed_pos": "PDV fechado dentro do mês",
}
FLAG_HELP = (
    "**O que significam os flags** (só destacam para a revisão humana; não bloqueiam):\n"
    + "\n".join(f"- `{flag}`: {text}" for flag, text in FLAG_MEANING.items())
    + "\n"
)

# (nome do dataset, título, arquivo .sql)
DATASETS: tuple[tuple[str, str, str], ...] = (
    ("ds_totals", "Totais e reconciliação", "totals"),
    ("ds_top20", "Top 20 maiores linhas", "top20"),
    ("ds_flagged", "Linhas com flag", "flagged"),
    ("ds_flag_counts", "Flags por tipo", "flag_counts"),
    ("ds_previous_totals", "Totais contra o mês anterior", "previous_totals"),
    ("ds_previous_pos", "PDVs contra o mês anterior", "previous_pos"),
)


def load_sql(stem: str) -> str:
    return (SQL_DIR / f"{stem}.sql").read_text(encoding="utf-8").strip()


def batch_query(stem: str) -> str:
    """A consulta restrita a um lote (parâmetro vinculado `:batch_id`), para o notebook."""
    return f"SELECT * FROM (\n{load_sql(stem)}\n) WHERE batch_id = :batch_id"  # noqa: S608


def check_batch_id(batch_id: str) -> str:
    if not _BATCH_ID.fullmatch(batch_id):
        raise ValueError(f"batch_id inválido: {batch_id!r} (esperado COM-YYYY-MM-vN)")
    return batch_id


def check_catalog(catalog: str) -> str:
    if catalog not in CATALOGS:
        raise ValueError(f"catalog inválido: {catalog!r} (esperado um de {sorted(CATALOGS)})")
    return catalog


def run(spark: Any, catalog: str, batch_id: str) -> dict[str, Any]:
    """Roda as consultas de um lote e devolve DataFrames por dataset (notebook)."""
    check_batch_id(batch_id)
    check_catalog(catalog)
    spark.sql(f"USE CATALOG {catalog}")
    spark.sql("USE SCHEMA commission")
    return {
        name: spark.sql(batch_query(stem), args={"batch_id": batch_id})
        for name, _, stem in DATASETS
    }


# --- dashboard -------------------------------------------------------------------------------

_BRL = {
    "type": "number-currency",
    "currencyCode": "BRL",
    "decimalPlaces": {"type": "fixed", "places": 2},
}
_INT = {"type": "number", "decimalPlaces": {"type": "max", "places": 0}}
_PCT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}


def _sql_lines(stem: str) -> list[str]:
    # `queryLines` são unidas sem separador: cada linha termina em "\n".
    return [line + "\n" for line in load_sql(stem).splitlines()]


def _text(name: str, line: str, y: int, height: int = 1) -> dict[str, Any]:
    return {
        "widget": {"name": name, "multilineTextboxSpec": {"lines": [line]}},
        "position": {"x": 0, "y": y, "width": 12, "height": height},
    }


def _counter(
    name: str, dataset: str, field: str, agg: str, title: str, fmt: dict[str, Any], x: int, y: int
) -> dict[str, Any]:
    key = f"{agg.lower()}({field})"
    return {
        "widget": {
            "name": name,
            "queries": [
                {
                    "name": "main_query",
                    "query": {
                        "datasetName": dataset,
                        "fields": [{"name": key, "expression": f"{agg}(`{field}`)"}],
                        "disaggregated": False,
                    },
                }
            ],
            "spec": {
                "version": 2,
                "widgetType": "counter",
                "encodings": {"value": {"fieldName": key, "displayName": title, "format": fmt}},
                "frame": {"showTitle": True, "title": title},
            },
        },
        "position": {"x": x, "y": y, "width": 3, "height": 3},
    }


def _table(
    name: str,
    dataset: str,
    title: str,
    columns: list[tuple[str, str, dict[str, Any] | None]],
    x: int,
    y: int,
    width: int,
    height: int,
) -> dict[str, Any]:
    cols = []
    for field, label, fmt in columns:
        col: dict[str, Any] = {"fieldName": field, "displayName": label}
        if fmt:
            col["format"] = fmt
        cols.append(col)
    return {
        "widget": {
            "name": name,
            "queries": [
                {
                    "name": "main_query",
                    "query": {
                        "datasetName": dataset,
                        "fields": [{"name": f, "expression": f"`{f}`"} for f, _, _ in columns],
                        "disaggregated": True,
                    },
                }
            ],
            "spec": {
                "version": 2,
                "widgetType": "table",
                "encodings": {"columns": cols},
                "frame": {"showTitle": True, "title": title},
            },
        },
        "position": {"x": x, "y": y, "width": width, "height": height},
    }


def _flag_bar() -> dict[str, Any]:
    return {
        "widget": {
            "name": "flag-counts",
            "queries": [
                {
                    "name": "main_query",
                    "query": {
                        "datasetName": "ds_flag_counts",
                        "fields": [
                            {"name": "flag", "expression": "`flag`"},
                            {"name": "sum(lines)", "expression": "SUM(`lines`)"},
                        ],
                        "disaggregated": False,
                    },
                }
            ],
            "spec": {
                "version": 3,
                "widgetType": "bar",
                "encodings": {
                    "x": {
                        "fieldName": "flag",
                        "displayName": "Flag",
                        "scale": {"type": "categorical", "sort": {"by": "y-reversed"}},
                    },
                    "y": {
                        "scale": {"type": "quantitative"},
                        "fields": [{"fieldName": "sum(lines)", "displayName": "Linhas"}],
                    },
                },
                "frame": {"showTitle": True, "title": "Linhas por flag"},
            },
        },
        "position": {"x": 0, "y": 20, "width": 4, "height": 7},
    }


def _batch_filter() -> dict[str, Any]:
    return {
        "widget": {
            "name": "f-batch",
            "queries": [
                {
                    "name": "q_batch",
                    "query": {
                        "datasetName": "ds_totals",
                        "fields": [{"name": "batch_id", "expression": "`batch_id`"}],
                        "disaggregated": False,
                    },
                }
            ],
            "spec": {
                "version": 2,
                "widgetType": "filter-single-select",
                "encodings": {
                    "fields": [
                        {"fieldName": "batch_id", "displayName": "Lote", "queryName": "q_batch"}
                    ]
                },
                "frame": {"showTitle": True, "title": "Lote (batch_id)"},
            },
        },
        "position": {"x": 0, "y": 0, "width": 4, "height": 2},
    }


def build_dashboard() -> dict[str, Any]:
    """O JSON do dashboard `commission_review` (formato Lakeview)."""
    datasets = [
        {"name": name, "displayName": title, "queryLines": _sql_lines(stem)}
        for name, title, stem in DATASETS
    ]
    layout: list[dict[str, Any]] = [
        _text("rv-title", "## Revisão do lote de comissão\n", 0),
        _text(
            "rv-sub",
            "**Escolha um lote** no filtro Lote: sem lote selecionado, os cartões somam todos "
            "os lotes. Somente leitura: este relatório não aprova nem altera nada "
            "(SPEC-003 §5). Dados sintéticos.",
            1,
        ),
        _counter(
            "rv-total-pos", "ds_totals", "total_pos_brl", "SUM", "Comissão de PDVs", _BRL, 0, 2
        ),
        _counter(
            "rv-total-dist",
            "ds_totals",
            "total_distributor_brl",
            "SUM",
            "Comissão de distribuidores",
            _BRL,
            3,
            2,
        ),
        _counter("rv-pos-lines", "ds_totals", "pos_lines", "SUM", "Linhas de PDV", _INT, 6, 2),
        _counter("rv-flagged", "ds_totals", "flagged_lines", "SUM", "Linhas com flag", _INT, 9, 2),
        _table(
            "rv-state",
            "ds_totals",
            "Estado e reconciliação (R$ 0,00 esperado em todas as diferenças)",
            [
                ("batch_id", "Lote", None),
                ("status", "Status", None),
                ("reference_month", "Mês", None),
                ("reconciliation_status", "Reconciliação", None),
                ("lines_compared", "Linhas comparadas", _INT),
                ("max_line_diff_brl", "Maior diferença por linha", _BRL),
                ("total_diff_brl", "Diferença no total", _BRL),
                ("pos_control_diff_brl", "Controle PDV", _BRL),
                ("distributor_control_diff_brl", "Controle distribuidor", _BRL),
                ("demo_mode", "Modo demo", None),
            ],
            0,
            5,
            12,
            4,
        ),
        _text("rv-top-h", "### Top 20 maiores linhas\n", 9),
        _table(
            "rv-top20",
            "ds_top20",
            "Top 20 por comissão",
            [
                ("rnk", "#", _INT),
                ("beneficiary_type", "Tipo", None),
                ("beneficiary_id", "Beneficiário", None),
                ("tier", "Faixa", None),
                ("base_amount_brl", "Base (R$)", _BRL),
                ("rate", "Taxa", _PCT),
                ("commission_brl", "Comissão (R$)", _BRL),
                ("flags", "Flags", None),
            ],
            0,
            10,
            12,
            6,
        ),
        _text("rv-flag-help", FLAG_HELP, 16, 4),
        _flag_bar(),
        _table(
            "rv-flagged-lines",
            "ds_flagged",
            "Linhas com flag (spike_3x, fractioning_suspect, tier_jump, closed_pos)",
            [
                ("beneficiary_id", "PDV", None),
                ("tier", "Faixa", None),
                ("base_amount_brl", "Base (R$)", _BRL),
                ("commission_brl", "Comissão (R$)", _BRL),
                ("flags", "Flags", None),
            ],
            4,
            20,
            8,
            7,
        ),
        _text(
            "rv-prev-h",
            "### Comparação com o mês anterior\n"
            "Lote de referência: o último `locked` do mês anterior (sem ele, colunas vazias).",
            27,
            2,
        ),
        _table(
            "rv-prev-totals",
            "ds_previous_totals",
            "Totais contra o lote anterior",
            [
                ("previous_batch_id", "Lote anterior", None),
                ("total_pos_brl", "PDVs (R$)", _BRL),
                ("previous_total_pos_brl", "PDVs anterior (R$)", _BRL),
                ("total_distributor_brl", "Distribuidores (R$)", _BRL),
                ("previous_total_distributor_brl", "Distribuidores anterior (R$)", _BRL),
            ],
            0,
            29,
            12,
            3,
        ),
        _table(
            "rv-prev-pos",
            "ds_previous_pos",
            "50 PDVs com maior mudança de comissão",
            [
                ("beneficiary_id", "PDV", None),
                ("previous_tier", "Faixa anterior", None),
                ("tier", "Faixa", None),
                ("previous_commission_brl", "Comissão anterior (R$)", _BRL),
                ("commission_brl", "Comissão (R$)", _BRL),
                ("change_brl", "Mudança (R$)", _BRL),
                ("flags", "Flags", None),
            ],
            0,
            32,
            12,
            8,
        ),
    ]
    pages: list[dict[str, Any]] = [
        {
            "name": "review",
            "displayName": "Revisão do lote",
            "pageType": "PAGE_TYPE_CANVAS",
            "layoutVersion": "GRID_V1",
            "layout": layout,
        },
        {
            "name": "filters",
            "displayName": "Filtros",
            "pageType": "PAGE_TYPE_GLOBAL_FILTERS",
            "layout": [_batch_filter()],
        },
    ]
    return {"datasets": datasets, "pages": pages}
