"""Checks estáticos do golden set (SPEC-008 §3, task P9.1). Sem workspace."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    path = ROOT / "scripts" / "check_golden_set.py"
    spec = importlib.util.spec_from_file_location("check_golden_set", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_golden_set"] = module
    spec.loader.exec_module(module)
    return module


check = _load()
CASES: list[dict[str, Any]] = check.load_cases()
SQL_CASES = [c for c in CASES if c["category"] != "refusal"]


def _names(view: str, kind: str) -> set[str]:
    data = yaml.safe_load((ROOT / "semantic" / f"{view}.yaml").read_text(encoding="utf-8"))
    return {item["name"] for item in data[kind]}


def test_counts_and_unique_ids() -> None:
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    by_category = {
        k: sum(c["category"] == k for c in CASES)
        for k in ("metric", "comparison", "refusal", "no_period")
    }
    assert by_category == {"metric": 20, "comparison": 5, "refusal": 5, "no_period": 1}


def test_no_period_case_has_no_month_in_the_question_and_a_month_sql() -> None:
    (case,) = [c for c in CASES if c["category"] == "no_period"]
    months = (
        "janeiro|fevereiro|março|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
    )
    assert not re.search(rf"20\d\d|\bmês\b|{months}", case["question"].lower())
    for field in ("reference_sql", "reference_month_sql"):
        sql = case[field]
        assert re.search(r"\batlas\.semantic\.mv_recharges\b", sql)
        assert "DATE'" not in sql  # o mês vem dos dados, não de uma data fixa
        assert re.search(r"ORDER BY recharge_month DESC LIMIT 1", sql)


@pytest.mark.parametrize(
    ("rows", "prefix"),
    [
        ([["2026-10-01"]], "ok"),
        ([], "FALHA"),
        ([["2026-10-01"], ["2026-09-01"]], "FALHA"),
        ([[None]], "FALHA"),
        ([["outubro"]], "FALHA"),
    ],
)
def test_check_month(rows: list[list[str | None]], prefix: str) -> None:
    assert check.check_month("GS-031", rows).startswith(prefix)


@pytest.mark.parametrize("case", SQL_CASES, ids=lambda c: c["id"])
def test_sql_case_shape(case: dict[str, Any]) -> None:
    view = case["expected_source_view"]
    assert view in {"mv_recharges", "mv_commission"}
    sql = case["reference_sql"]
    assert re.search(rf"\batlas\.semantic\.{view}\b", sql)
    # só `atlas.semantic`: o golden set respeita a regra de leitura única (tech-stack)
    assert not re.search(r"\batlas\.(gold|silver|bronze|commission)\b", sql)
    assert re.search(r"AS value\b", sql)
    assert case["tolerance_pct"] > 0
    for name in re.findall(r"MEASURE\((\w+)\)", sql):
        assert name in _names(view, "measures"), f"{case['id']}: medida {name} não existe"
    # colunas do WHERE e do GROUP BY precisam ser dimensões da view
    dimensions = _names(view, "dimensions")
    for name in re.findall(r"^\s*(?:WHERE|AND)?\s*(\w+) (?:=|IN) ", sql, flags=re.M):
        if name not in {"WHERE", "AND"}:
            assert name in dimensions, f"{case['id']}: dimensão {name} não existe em {view}"
    for name in re.findall(r"GROUP BY (\w+)", sql):
        assert name in dimensions, f"{case['id']}: dimensão {name} não existe em {view}"


@pytest.mark.parametrize(
    "case", [c for c in CASES if c["category"] == "refusal"], ids=lambda c: c["id"]
)
def test_refusal_case_shape(case: dict[str, Any]) -> None:
    assert case["expected_behavior"] == "refuse"
    assert case["forbidden_tools"] == ["*"]
    assert "reference_sql" not in case


def test_for_catalog_swaps_only_the_semantic_catalog() -> None:
    sql = "SELECT MEASURE(x) FROM atlas.semantic.mv_recharges"
    assert (
        check.for_catalog(sql, "atlas_dev")
        == "SELECT MEASURE(x) FROM atlas_dev.semantic.mv_recharges"
    )


@pytest.mark.parametrize(
    ("rows", "prefix"),
    [
        ([["123.45"]], "ok"),
        ([["-3.2"]], "ok"),
        ([], "FALHA"),
        ([["1"], ["2"]], "FALHA"),
        ([["1", "2"]], "FALHA"),
        ([[None]], "FALHA"),
        ([["abc"]], "FALHA"),
    ],
)
def test_check_value(rows: list[list[str | None]], prefix: str) -> None:
    assert check.check_value("GS-001", rows).startswith(prefix)


def test_region_filters_use_ibge_region_codes() -> None:
    # `region` é gravado como código (data/reference/municipalities_ibge.csv), não como nome
    valid = {"N", "NE", "CO", "SE", "S"}
    for case in SQL_CASES:
        for value in re.findall(r"\bregion = '(\w+)'", case["reference_sql"]):
            assert value in valid, f"{case['id']}: região {value!r} não é um código IBGE"
