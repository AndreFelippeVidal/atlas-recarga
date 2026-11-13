"""Partes puras do rascunho (task P8.3). O cálculo em Spark é conferido no workspace."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from commission import draft


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 11, 13, 12, 0, tzinfo=UTC), date(2026, 10, 1)),
        (datetime(2027, 1, 1, 12, 0, tzinfo=UTC), date(2026, 12, 1)),
        # 02:00 UTC de 1º/11 ainda é 31/10 em São Paulo: o mês corrente é outubro
        (datetime(2026, 11, 1, 2, 0, tzinfo=UTC), date(2026, 9, 1)),
    ],
)
def test_default_reference_month_is_previous_civil_month_in_sao_paulo(
    now: datetime, expected: date
) -> None:
    assert draft.default_reference_month(now) == expected


NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def test_resolve_accepts_blank_and_closed_months() -> None:
    assert draft.resolve_reference_month("", NOW) == date(2026, 10, 1)
    assert draft.resolve_reference_month("2026-03", NOW) == date(2026, 3, 1)


@pytest.mark.parametrize(
    "text", ["2026-11", "2027-01", "2026-13", "2026-1", "out/2026", "2026-10-01"]
)
def test_resolve_rejects_open_future_or_malformed_months(text: str) -> None:
    with pytest.raises(ValueError):
        draft.resolve_reference_month(text, NOW)


def test_batch_id_format() -> None:
    assert draft.batch_id_for(date(2026, 10, 1)) == "COM-2026-10-v1"
    assert draft.batch_id_for(date(2026, 3, 1), 2) == "COM-2026-03-v2"


@pytest.mark.parametrize("name", ["atlas_dev", "atlas"])
def test_identifier_ok(name: str) -> None:
    assert draft.check_identifier(name, "catalog") == name


@pytest.mark.parametrize("name", ["atlas; DROP", "Atlas", "1atlas", ""])
def test_identifier_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        draft.check_identifier(name, "catalog")
