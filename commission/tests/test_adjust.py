"""Lote de ajuste ADJ (SPEC-003 §7, task P8.10). O Spark é conferido no workspace."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from commission import adjust, flags, lock, reconcile, review
from commission.adjust import Line

D = Decimal
ROOT = Path(__file__).resolve().parents[2]


def _pos(pos_id: str, base: str, commission: str, tier: str = "bronze", rate: str = "0.02") -> Line:
    return Line("pos", pos_id, D(base), tier, D(rate), D(commission))


def _dist(dist_id: str, base: str, commission: str) -> Line:
    return Line("distributor", dist_id, D(base), None, D("0.03"), D(commission))


def _month(volumes: dict[str, str], owner: dict[str, str]) -> dict[adjust.Key, Line]:
    return adjust.recompute({k: D(v) for k, v in volumes.items()}, owner)


OWNER = {"P1": "D1", "P2": "D1", "P3": "D2"}


def test_ids_and_numbering() -> None:
    month = date(2026, 10, 1)
    assert adjust.adjustment_id(month, 1) == "COM-2026-10-ADJ-1"
    assert adjust.is_adjustment("COM-2026-10-ADJ-2")
    assert not adjust.is_adjustment("COM-2026-10-v1")
    assert adjust.month_of("COM-2026-10-v1") == month
    assert adjust.month_of("COM-2026-10-ADJ-3") == month
    with pytest.raises(ValueError):
        adjust.month_of("COM-2026-13-v1")
    ids = ["COM-2026-10-v1", "COM-2026-10-ADJ-1", "COM-2026-10-ADJ-2"]
    assert adjust.next_adjustment_number(ids) == 3
    assert adjust.next_adjustment_number(["COM-2026-10-v1"]) == 1


def test_recompute_follows_the_rules_and_tier_boundaries() -> None:
    lines = _month({"P1": "4999.99", "P2": "5000.00", "P3": "0.00"}, OWNER)
    assert lines[("pos", "P1")].commission_brl == D("100.00")  # bronze 2%
    assert lines[("pos", "P2")].commission_brl == D("150.00")  # prata 3%
    assert ("pos", "P3") not in lines  # volume zero não gera linha
    assert lines[("distributor", "D1")].base_amount_brl == D("9999.99")
    assert lines[("distributor", "D1")].commission_brl == D("300.00")  # 299.9997 -> 300.00
    assert ("distributor", "D2") not in lines


def test_pos_without_distributor_is_refused() -> None:
    with pytest.raises(RuntimeError, match="sem distribuidor"):
        adjust.recompute({"P9": D("10.00")}, OWNER)


def test_no_difference_means_no_lines() -> None:
    month = _month({"P1": "1000.00", "P2": "6000.00"}, OWNER)
    assert adjust.diff_lines(adjust.net_locked(month.values()), month) == []


def test_negative_and_positive_differences() -> None:
    locked = _month({"P1": "6000.00", "P2": "1000.00"}, OWNER)  # P1 prata
    fresh = _month({"P1": "4000.00", "P2": "1500.00", "P3": "500.00"}, OWNER)
    diff = {(x.beneficiary_type, x.beneficiary_id): x for x in adjust.diff_lines(locked, fresh)}

    # P1 caiu de prata (3%) para bronze (2%): -180.00 + 80.00 = -100.00 na comissão
    assert diff[("pos", "P1")].base_amount_brl == D("-2000.00")
    assert diff[("pos", "P1")].commission_brl == D("-100.00")
    assert diff[("pos", "P1")].tier == "bronze"  # faixa do recálculo
    assert diff[("pos", "P2")].commission_brl == D("10.00")
    assert diff[("pos", "P3")].commission_brl == D("10.00")  # PDV novo conta inteiro
    assert diff[("distributor", "D1")].base_amount_brl == D("-1500.00")
    assert diff[("distributor", "D1")].commission_brl == D("-45.00")
    assert diff[("distributor", "D2")].commission_brl == D("15.00")


def test_beneficiary_that_vanished_is_reversed_with_its_last_tier() -> None:
    locked = _month({"P1": "6000.00", "P3": "1000.00"}, OWNER)
    fresh = _month({"P1": "6000.00"}, OWNER)
    diff = adjust.diff_lines(locked, fresh)
    by_key = {(x.beneficiary_type, x.beneficiary_id): x for x in diff}
    assert set(by_key) == {("pos", "P3"), ("distributor", "D2")}
    assert by_key[("pos", "P3")].commission_brl == D("-20.00")
    assert by_key[("pos", "P3")].tier == "bronze"
    assert by_key[("pos", "P3")].rate == D("0.02")  # rate nunca fica nulo


def test_locked_plus_adjustment_equals_the_recompute() -> None:
    """O invariante da reconciliação do ajuste (§7), no Python."""
    original = _month({"P1": "6000.00", "P2": "1000.00"}, OWNER)
    fresh = _month({"P1": "4000.00", "P2": "1500.00", "P3": "500.00"}, OWNER)
    adj = adjust.diff_lines(original, fresh)
    net = adjust.net_locked([*original.values(), *adj])
    for key, line in fresh.items():
        assert net[key].base_amount_brl == line.base_amount_brl
        assert net[key].commission_brl == line.commission_brl
    for key, line in net.items():
        if key not in fresh:
            assert line.base_amount_brl == D("0.00")
            assert line.commission_brl == D("0.00")


def test_second_adjustment_is_computed_against_the_accumulated_net() -> None:
    original = _month({"P1": "6000.00"}, OWNER)
    first = _month({"P1": "4000.00"}, OWNER)
    adj1 = adjust.diff_lines(original, first)
    net = adjust.net_locked([*original.values(), *adj1])
    # o gold volta ao valor original: o segundo ajuste desfaz exatamente o primeiro
    adj2 = adjust.diff_lines(net, original)
    assert adjust.net_locked([*original.values(), *adj1, *adj2])[("pos", "P1")].commission_brl == (
        original[("pos", "P1")].commission_brl
    )
    assert adjust.diff_lines(adjust.net_locked([*original.values(), *adj1, *adj2]), original) == []


def test_totals_split_by_beneficiary_type() -> None:
    diff = [
        _pos("P1", "-2000.00", "-100.00"),
        _pos("P2", "500.00", "10.00"),
        _dist("D1", "1", "-15.00"),
    ]
    assert adjust.totals(diff) == (D("-90.00"), D("-15.00"))


def test_negative_lines_pass_the_lock_checks_and_the_remittance() -> None:
    rows = [
        ("pos", "P1", D("-100.00")),
        ("pos", "P2", D("10.00")),
        ("distributor", "D1", D("-15.00")),
    ]
    lock.check_totals(rows, D("-90.00"), D("-15.00"))
    csv = lock.render_remittance(rows).decode()
    assert "pos,P1,-100.00" in csv
    with pytest.raises(RuntimeError):
        lock.check_totals(rows, D("-90.01"), D("-15.00"))


def test_review_accepts_the_adjustment_batch_id() -> None:
    assert review._BATCH_ID.fullmatch("COM-2026-10-ADJ-1")


def test_adjustment_reconciliation_sql_uses_the_accumulated_net() -> None:
    sql = reconcile.recompute_sql("atlas_dev", adjustment=True)
    assert "{" not in sql
    assert "locked_lines" in sql and "h.status = 'locked'" in sql
    assert "l.batch_id <> :batch_id" in sql
    # a regular continua igual: sem locked_lines
    assert "locked_lines" not in reconcile.recompute_sql("atlas_dev")
    # ambas usam o mesmo recálculo independente sobre fct_recharges e as mesmas faixas
    assert "fct_recharges" in sql
    assert "agg_pos_month" not in sql


def _expected_part(sql: str) -> str:
    return sql[sql.index("pos_volume AS") : sql.index("actual AS")]


def test_expected_tiers_are_the_same_in_both_sql_variants() -> None:
    a = reconcile.recompute_sql("c")
    b = reconcile.recompute_sql("c", adjustment=True)
    assert _expected_part(a) == _expected_part(b)


class _Row(dict[str, Any]):
    pass


class _Result:
    def __init__(self, rows: list[_Row]) -> None:
        self.rows = rows

    def first(self) -> _Row | None:
        return self.rows[0] if self.rows else None

    def collect(self) -> list[_Row]:
        return self.rows


class _Spark:
    def __init__(self, status: str) -> None:
        self.status = status
        self.calls: list[str] = []

    def sql(self, query: str, args: dict[str, Any] | None = None) -> _Result:
        self.calls.append(query)
        return _Result([_Row(status=self.status)])


def test_flags_do_not_apply_to_an_adjustment() -> None:
    spark = _Spark("draft")
    counts = flags.flag_draft(spark, "atlas_dev", "COM-2026-10-ADJ-1")
    assert set(counts.values()) == {0}
    assert len(spark.calls) == 1  # só leu o status; nenhum flag foi gravado


def test_job_passes_adjust_batch_id_to_the_three_tasks() -> None:
    text = (ROOT / "databricks.yml").read_text(encoding="utf-8")
    job = text[text.index("atlas_commission_draft:") : text.index("atlas_commission_review:")]
    assert "name: adjust_batch_id" in job
    assert len(re.findall(r"job\.parameters\.adjust_batch_id", job)) == 3


def test_locked_lines_are_never_updated_by_the_adjustment_module() -> None:
    source = (ROOT / "commission" / "adjust.py").read_text(encoding="utf-8")
    assert not re.search(r"(UPDATE|DELETE FROM)\s+\S*locked_lines", source)
