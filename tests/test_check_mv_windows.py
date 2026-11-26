"""`scripts/check_mv_windows.py` (SPEC-004 §5 e §8, task P15.5). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_mv_windows", ROOT / "scripts" / "check_mv_windows.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_mv_windows"] = module
    spec.loader.exec_module(module)
    return module


cw = _load()


def test_monthly_query_compares_the_three_measures_with_the_gold_windows() -> None:
    query = cw.build_monthly_query("atlas_dev")
    for measure in ("gross_revenue_t3m", "gross_revenue_ytd", "revenue_mom_change"):
        assert f"MEASURE({measure})" in query
    assert "atlas_dev.semantic.mv_recharges" in query
    assert "atlas_dev.gold.fct_recharges" in query
    assert "FULL OUTER JOIN" in query
    assert "RANGE BETWEEN 2 PRECEDING AND CURRENT ROW" in query  # janela de 3 meses
    assert "PARTITION BY yr" in query  # o YTD zera a cada janeiro
    assert "NULLIF(direct.prev, 0)" in query
    assert "f.status = 'approved'" in query
    assert "GROUP BY recharge_month" in query and "recharge_month =" not in query


def test_filters_apply_to_both_sides_and_are_escaped() -> None:
    query = cw.build_monthly_query("atlas_dev", "pharmacy", "D'Avila {x}")
    assert "WHERE pos_type = 'pharmacy' AND distributor_name = 'D''Avila {x}'" in query
    assert "p.pos_type = 'pharmacy' AND d.distributor_name = 'D''Avila {x}'" in query
    assert cw.mv_where() == ""
    assert cw.mv_where("2026-10-01") == "WHERE recharge_month = DATE'2026-10-01'"


def test_uf_query_uses_the_consumer_form_month_filter_with_group_by() -> None:
    query = cw.build_uf_query("atlas_dev", "2026-10-01", "pharmacy")
    assert "WHERE recharge_month = DATE'2026-10-01' AND pos_type = 'pharmacy' GROUP BY uf" in query
    assert "PARTITION BY uf, yr" in query
    assert "WHERE m = DATE'2026-10-01'" in query  # o gold calcula todos os meses e filtra no fim
    assert "(SELECT MEASURE" not in query


def test_money_is_exact_to_the_cent_and_gold_null_counts_as_zero_for_t3m() -> None:
    assert cw.money_equal("100.00", "100.0")
    assert not cw.money_equal("100.01", "100.00")
    assert cw.money_equal("0.00", None)  # achado 2 do spike P15.2
    assert not cw.money_equal(None, "0.00")
    assert not cw.money_equal("x", "1")
    assert not cw.money_equal("NaN", "NaN")


def test_ytd_needs_both_sides_to_agree_including_null() -> None:
    assert cw.ytd_equal("10.00", "10")
    assert cw.ytd_equal(None, None)
    assert not cw.ytd_equal("0.00", None)


def test_mom_is_equal_to_four_decimals_and_null_only_matches_null() -> None:
    assert cw.mom_equal("0.123449", "0.12345")
    assert not cw.mom_equal("0.1234", "0.1236")
    assert cw.mom_equal(None, None)  # primeiro mês ou base zero
    assert not cw.mom_equal(None, "0.1")
    assert not cw.mom_equal("0.1", None)
    assert not cw.mom_equal("abc", None)


def _row(key: str, **kw: str | None) -> list[str | None]:
    base: dict[str, str | None] = {"t3m": "300.00", "ytd": "300.00", "mom": "0.1000"}
    base.update(kw)
    return [key, base["t3m"], "300.00", base["ytd"], "300.00", base["mom"], "0.10"]


def test_compare_lines_flag_each_failing_measure_and_empty_input() -> None:
    lines = cw.compare_lines("[x] mês", [_row("2026-10-01"), _row("2026-11-01", ytd="299.99")])
    assert lines[0].startswith("ok")
    assert lines[1].startswith("FALHA (ytd)")
    assert cw.compare_lines("[x] mês", [])[0].startswith("FALHA")
    first_month = ["2025-11-01", "10.00", "10.00", "10.00", "10.00", None, None]
    assert cw.compare_lines("[x] mês", [first_month])[0].startswith("ok")


def test_run_check_covers_three_cuts_monthly_and_by_uf(monkeypatch: pytest.MonkeyPatch) -> None:
    statements: list[str] = []

    def fake_run(profile: str, warehouse: str, statement: str) -> list[list[str | None]]:
        statements.append(statement)
        if "distributor_name, SUM" in statement:
            return [["Abreu", "1.00"]]
        return [_row("2026-10-01")]

    monkeypatch.setattr(cw, "_run", fake_run)
    monkeypatch.setattr(cw, "MONTHS", 1)
    lines = cw.run_check("atlas_dev", "p", "w")
    assert len(statements) == 1 + 3 * 2  # distribuidor + (mês a mês e UF) x 3 recortes
    assert all(line.startswith("ok") for line in lines)
    assert any("[distribuidor=Abreu]" in line for line in lines)
    assert any("pos_type=pharmacy" in line for line in lines)
    assert "distributor_name = 'Abreu'" in statements[-1]


def test_run_check_fails_without_distributor_and_main_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cw, "MONTHS", 1)
    monkeypatch.setattr(cw, "_run", lambda *_: [])
    assert cw.run_check("atlas_dev", "p", "w")[0].startswith("FALHA")
    argv = ["--target", "dev", "--profile", "p", "--warehouse-id", "w", "--distributor", "A"]
    monkeypatch.setattr(cw, "_run", lambda *_: [_row("2026-10-01")])
    assert cw.main(argv) == 0
    monkeypatch.setattr(cw, "_run", lambda *_: [_row("2026-10-01", t3m="1.00")])
    assert cw.main(argv) == 1


def test_fewer_than_twelve_months_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cw, "_run", lambda *_: [_row("2026-10-01")])
    lines = cw.run_check("atlas_dev", "p", "w", distributor="A")
    assert sum("1 meses comparados, esperado 12" in line for line in lines) == 3
