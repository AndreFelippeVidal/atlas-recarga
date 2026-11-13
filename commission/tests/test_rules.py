from decimal import Decimal as D

import pytest

from commission import rules


@pytest.mark.parametrize(
    ("volume", "tier", "commission"),
    [
        ("0.01", "bronze", "0.00"),
        ("4999.99", "bronze", "100.00"),  # SPEC-003 §8
        ("5000.00", "silver", "150.00"),  # SPEC-003 §8
        ("19999.99", "silver", "600.00"),
        ("20000.00", "gold", "800.00"),
        ("49999.99", "gold", "2000.00"),
        ("50000.00", "diamond", "2500.00"),
        ("1000000.00", "diamond", "50000.00"),
    ],
)
def test_pos_tier_boundaries(volume: str, tier: str, commission: str) -> None:
    t, c = rules.pos_commission(D(volume))
    assert t.name == tier
    assert c == D(commission)


def test_tier_is_whole_not_progressive() -> None:
    # 50.000 inteiros a 5%, não 5k·2% + 15k·3% + ...
    assert rules.pos_commission(D("50000.00"))[1] == D("2500.00")


def test_half_even_rounding() -> None:
    # empates vão para o centavo par; 2% de 0.75 = 0.015 -> 0.02
    assert rules.round_brl(D("0.005")) == D("0.00")
    assert rules.round_brl(D("0.015")) == D("0.02")
    assert rules.round_brl(D("0.025")) == D("0.02")
    assert rules.round_brl(D("0.035")) == D("0.04")
    assert rules.pos_commission(D("0.75"))[1] == D("0.02")


def test_distributor_three_percent() -> None:
    assert rules.distributor_commission(D("100000.00")) == D("3000.00")
    assert rules.distributor_commission(D("0.50")) == D("0.02")  # 0.015 -> 0.02
    assert rules.distributor_commission(D("0.25")) == D("0.01")  # 0.0075 -> 0.01


def test_zero_volume_has_no_line() -> None:
    assert not rules.has_line(D("0"))
    assert rules.has_line(D("0.01"))


def test_negative_volume_is_error() -> None:
    for fn in (rules.tier_for, rules.distributor_commission, rules.has_line):
        with pytest.raises(ValueError, match="volume"):
            fn(D("-0.01"))


def test_batch_total_is_sum_of_rounded_lines() -> None:
    lines = [rules.pos_commission(D("0.75"))[1]] * 3  # 3 x 0.02
    assert rules.batch_total(lines) == D("0.06")
    # recalcular o total daria 3 * 0.0150 = 0.045 -> 0.04: difere de propósito
    assert rules.round_brl(D("0.75") * D("0.02") * 3) == D("0.04")
    assert rules.batch_total([]) == D("0.00")


def test_zero_boundaries() -> None:
    assert rules.tier_for(D("0")).name == "bronze"
    assert rules.distributor_commission(D("0")) == D("0.00")
    assert rules.pos_commission(D("0"))[1] == D("0.00")
    with pytest.raises(ValueError, match="volume"):
        rules.pos_commission(D("-0.01"))
