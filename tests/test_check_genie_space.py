"""Checks of `scripts/check_genie_space.py` (P7.5). No workspace needed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "check_genie_space", ROOT / "scripts" / "check_genie_space.py"
)
assert spec and spec.loader
check = importlib.util.module_from_spec(spec)
sys.modules["check_genie_space"] = check
spec.loader.exec_module(check)

GOOD = (
    "SELECT ddd, MEASURE(gross_revenue) FROM atlas_dev.semantic.mv_recharges "
    "WHERE recharge_month = DATE'2026-10-01' GROUP BY ddd"
)


def test_good_sql_passes_every_check() -> None:
    assert all(line.startswith("ok") for line in check.evaluate(GOOD))


def test_missing_sql_fails() -> None:
    assert check.evaluate(None)[0].startswith("FALHA")


def test_sql_without_ddd_or_measure_fails() -> None:
    lines = check.evaluate("SELECT SUM(amount_brl) FROM atlas_dev.semantic.mv_recharges")
    assert sum(line.startswith("FALHA") for line in lines) == 2


def test_reading_the_gold_layer_fails() -> None:
    sql = f"{GOOD} UNION ALL SELECT ddd, 1 FROM atlas_dev.gold.dim_municipality"  # noqa: S608
    assert any(line.startswith("FALHA") and "gold" in line for line in check.evaluate(sql))


def test_extract_sql_reads_the_first_query_attachment() -> None:
    message = {"attachments": [{"text": {"content": "oi"}}, {"query": {"query": GOOD}}]}
    assert check.extract_sql(message) == GOOD
    assert check.extract_sql({"attachments": []}) is None


def test_find_space_id_accepts_a_dev_prefixed_title() -> None:
    response = {"spaces": [{"space_id": "a1", "title": "[dev x] Atlas Recarga"}]}
    assert check.find_space_id(response) == "a1"
    assert check.find_space_id({"spaces": [{"space_id": "b2", "title": "Outro"}]}) is None


def test_find_space_id_refuses_ambiguity() -> None:
    response = {"spaces": [{"space_id": "a", "title": "Atlas Recarga"}] * 2}
    with pytest.raises(RuntimeError):
        check.find_space_id(response)


def test_ddd_only_in_select_fails_the_group_by_check() -> None:
    lines = check.evaluate("SELECT ddd, MEASURE(gross_revenue) FROM x.semantic.mv_recharges")
    assert any(line.startswith("FALHA") and "ddd" in line for line in lines)


def test_unqualified_gold_table_is_a_leak() -> None:
    assert any(line.startswith("FALHA") for line in check.evaluate(GOOD + " JOIN gold.dim_pos"))


def test_backticked_sql_as_generated_by_genie_passes() -> None:
    sql = (
        "SELECT `ddd`, MEASURE(`gross_revenue`) AS `gross_revenue` FROM "
        "`atlas_dev`.`semantic`.`mv_recharges` WHERE `recharge_month` = DATE'2026-10-01' "
        "GROUP BY `ddd` ORDER BY `gross_revenue` DESC"
    )
    assert all(line.startswith("ok") for line in check.evaluate(sql))
    qualified = "SELECT ddd, MEASURE(`mv_recharges`.`gross_revenue`) FROM mv_recharges GROUP BY ddd"
    assert all(line.startswith("ok") for line in check.evaluate(qualified))
