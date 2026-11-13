"""Check do rascunho (task P8.3): as consultas e a validação do id. Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_commission_draft", ROOT / "scripts" / "check_commission_draft.py"
)
assert _spec is not None
assert _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
sys.modules["check_commission_draft"] = check
_spec.loader.exec_module(check)


def test_queries_target_the_given_batch_and_catalog() -> None:
    sql = check.queries("atlas_dev", "COM-2026-10-v1")
    assert set(sql) == {"header", "sums", "gold_volume", "bad_lines", "events", "events_total"}
    assert all("COM-2026-10-v1" in text for text in sql.values())
    assert "atlas_dev.gold.agg_pos_month" in sql["gold_volume"]
    assert "'diamond' THEN 0.0500" in sql["bad_lines"]


@pytest.mark.parametrize(
    "value", ["COM-2026-10-v1; DROP", "COM-2026-13-v1", "x", "COM-2026-10-ADJ-1"]
)
def test_batch_id_is_validated(value: str) -> None:
    with pytest.raises(ValueError):
        check.queries("atlas_dev", value)


def test_tier_rates_match_the_rules_module() -> None:
    from decimal import Decimal

    from commission import rules

    expected = {t.name: t.rate for t in rules.TIERS}
    assert {name: Decimal(rate) for name, rate in check.TIER_RATES.items()} == expected
