"""Partes puras da reconciliação (task P8.4). O recálculo em SQL é conferido no workspace."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from commission import reconcile, rules


def _result(**overrides: object) -> reconcile.Result:
    values: dict[str, object] = {
        "batch_id": "COM-2026-10-v1",
        "lines_compared": 4798,
        "max_line_diff_brl": Decimal("0.00"),
        "total_diff_brl": Decimal("0.00"),
        "pos_control_diff_brl": Decimal("0.00"),
        "distributor_control_diff_brl": Decimal("0.00"),
    }
    values.update(overrides)
    return reconcile.Result(**values)  # type: ignore[arg-type]


def test_passes_only_when_every_difference_is_zero() -> None:
    assert _result().status == "passed"


@pytest.mark.parametrize(
    "field",
    ["max_line_diff_brl", "total_diff_brl", "pos_control_diff_brl", "distributor_control_diff_brl"],
)
@pytest.mark.parametrize("diff", [Decimal("0.01"), Decimal("-0.01")])
def test_any_nonzero_difference_fails(field: str, diff: Decimal) -> None:
    assert _result(**{field: diff}).status == "failed"


def test_batch_without_lines_fails() -> None:
    assert _result(lines_compared=0).status == "failed"


def test_sql_is_independent_of_the_main_calculation() -> None:
    sql = reconcile.recompute_sql("atlas_dev")
    assert "gold.fct_recharges" in sql
    assert "agg_pos_month" not in sql
    assert "atlas_dev.commission.batch_lines" in sql
    assert ":batch_id" in sql and "{" not in sql


def test_sql_tiers_match_rules() -> None:
    """A tabela escrita no SQL tem de coincidir com `rules.TIERS` (SPEC-003 §2)."""
    sql = reconcile.RECOMPUTE_SQL
    found = re.findall(r"WHEN base >= ([\d.]+) THEN ([\d.]+)", sql)
    found.append(("0", re.search(r"ELSE ([\d.]+) END", sql).group(1)))  # type: ignore[union-attr]
    in_sql = {(Decimal(floor), Decimal(rate)) for floor, rate in found}
    assert in_sql == {(t.floor, t.rate) for t in rules.TIERS}
    assert "SUM(v.base) * 0.03" in sql
    assert Decimal("0.03") == rules.DISTRIBUTOR_RATE


@pytest.mark.parametrize("catalog", ["atlas; DROP", "Atlas", ""])
def test_rejects_bad_catalog(catalog: str) -> None:
    with pytest.raises(ValueError):
        reconcile.recompute_sql(catalog)
