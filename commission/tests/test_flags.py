"""Partes puras dos flags de revisão (task P8.5). O SQL roda no workspace."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from commission import flags, rules


def test_sql_reads_only_gold_and_writes_only_batch_lines() -> None:
    sql = flags.flags_sql("atlas_dev")
    assert "atlas_dev.gold.fct_recharges" in sql
    assert "agg_pos_month" not in sql and "silver" not in sql and "bronze" not in sql
    assert re.findall(r"MERGE INTO (\S+)", sql) == ["atlas_dev.commission.batch_lines"]
    assert ":batch_id" in sql and "{" not in sql


def test_sql_has_the_four_flags() -> None:
    sql = flags.flags_sql("atlas_dev")
    for name in flags.FLAG_ORDER:
        assert f"'{name}'" in sql


def test_tier_expressions_match_rules() -> None:
    rate = flags._tier_expr("rate")
    index = flags._tier_expr("index")
    found = {
        (Decimal(floor), Decimal(value))
        for floor, value in re.findall(r"WHEN base >= ([\d.]+) THEN ([\d.]+)", rate)
    }
    found.add((Decimal(0), Decimal(re.search(r"ELSE ([\d.]+) END", rate).group(1))))  # type: ignore[union-attr]
    assert found == {(t.floor, t.rate) for t in rules.TIERS}
    ordered = sorted(rules.TIERS, key=lambda t: t.floor)
    by_floor = {
        Decimal(floor): int(i)
        for floor, i in re.findall(r"WHEN base >= ([\d.]+) THEN (\d+)", index)
    }
    assert by_floor == {t.floor: ordered.index(t) for t in ordered if t.floor > 0}
    assert "ELSE 0 END" in index


def test_thresholds_follow_the_spec() -> None:
    assert flags.SPIKE_FACTOR == 3
    assert flags.SPIKE_HISTORY_MONTHS == 3
    assert flags.TIER_JUMP_STEPS == 2
    assert flags.FRACTION_MIN_COUNT == 21  # mais de 20
    assert flags.FRACTION_WINDOW_MICROS == 599_999_999  # estritamente menos de 10 min
    assert flags.FRACTION_AMOUNT == 10


@pytest.mark.parametrize("catalog", ["atlas; DROP", "Atlas", ""])
def test_rejects_bad_catalog(catalog: str) -> None:
    with pytest.raises(ValueError):
        flags.flags_sql(catalog)


class _Rows:
    def __init__(self, row: dict[str, str] | None) -> None:
        self._row = row

    def first(self) -> dict[str, str] | None:
        return self._row


class _FakeSpark:
    def __init__(self, row: dict[str, str] | None) -> None:
        self.row = row
        self.statements: list[str] = []

    def sql(self, statement: str, args: dict[str, str] | None = None) -> _Rows:
        self.statements.append(statement)
        return _Rows(self.row)


def test_flag_draft_refuses_missing_batch() -> None:
    spark = _FakeSpark(None)
    with pytest.raises(RuntimeError, match="não existe"):
        flags.flag_draft(spark, "atlas_dev", "COM-2026-10-v1")
    assert not any("MERGE" in s for s in spark.statements)


@pytest.mark.parametrize("status", ["under_review", "approved", "locked"])
def test_flag_draft_refuses_batch_that_is_not_draft(status: str) -> None:
    spark = _FakeSpark({"status": status})
    with pytest.raises(RuntimeError, match="só se marca um draft"):
        flags.flag_draft(spark, "atlas_dev", "COM-2026-10-v1")
    assert not any("MERGE" in s for s in spark.statements)
