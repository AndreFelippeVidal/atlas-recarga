"""Checks of the committed IBGE reference snapshot (SPEC-001 §4, task P4.2).

Reads only the CSV in the repo: no network, no script run.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

REFERENCE = Path(__file__).resolve().parents[1] / "data" / "reference" / "municipalities_ibge.csv"
COLUMNS = ["municipality_ibge_code", "municipality_name", "uf", "region", "population", "ddd"]
UFS = {
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
}  # fmt: skip


@pytest.fixture(scope="module")
def rows() -> list[dict[str, str]]:
    with REFERENCE.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == COLUMNS
        return list(reader)


def test_has_5570_rows(rows: list[dict[str, str]]) -> None:
    assert len(rows) == 5570


def test_codes_are_unique(rows: list[dict[str, str]]) -> None:
    codes = [r["municipality_ibge_code"] for r in rows]
    assert len(set(codes)) == len(codes)


def test_codes_have_7_digits(rows: list[dict[str, str]]) -> None:
    for r in rows:
        code = r["municipality_ibge_code"]
        assert len(code) == 7
        assert code.isdigit()


def test_all_27_ufs_present(rows: list[dict[str, str]]) -> None:
    assert {r["uf"] for r in rows} == UFS


def test_uf_matches_code_prefix(rows: list[dict[str, str]]) -> None:
    by_prefix: dict[str, set[str]] = {}
    for r in rows:
        by_prefix.setdefault(r["municipality_ibge_code"][:2], set()).add(r["uf"])
    assert all(len(ufs) == 1 for ufs in by_prefix.values())


def test_regions_are_valid(rows: list[dict[str, str]]) -> None:
    assert {r["region"] for r in rows} == {"N", "NE", "CO", "SE", "S"}


def test_population_is_positive_integer(rows: list[dict[str, str]]) -> None:
    for r in rows:
        assert r["population"].isdigit()
        assert int(r["population"]) > 0


def test_ddd_has_2_digits(rows: list[dict[str, str]]) -> None:
    for r in rows:
        assert len(r["ddd"]) == 2
        assert r["ddd"].isdigit()


def test_known_municipalities(rows: list[dict[str, str]]) -> None:
    by_code = {r["municipality_ibge_code"]: r for r in rows}
    sao_paulo = by_code["3550308"]
    assert (sao_paulo["uf"], sao_paulo["ddd"]) == ("SP", "11")
    assert by_code["1302603"]["ddd"] == "92"  # Manaus
    assert by_code["4106902"]["ddd"] == "41"  # Curitiba
    assert by_code["2927408"]["ddd"] == "71"  # Salvador


def test_ddd_follows_immediate_region_table(rows: list[dict[str, str]]) -> None:
    """Cities where the DDD differs from the UF default exercise the region table."""
    by_code = {r["municipality_ibge_code"]: r for r in rows}
    assert by_code["3136702"]["ddd"] == "32"  # Juiz de Fora (MG default 31)
    assert by_code["3548500"]["ddd"] == "13"  # Santos (SP default 11)
    assert by_code["2611101"]["ddd"] == "87"  # Petrolina (PE default 81)
    assert by_code["4108304"]["ddd"] == "45"  # Foz do Iguaçu (PR default 41)
