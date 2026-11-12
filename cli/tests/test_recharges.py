from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow.compute as pc
import pyarrow.dataset as ds
import pytest
from atlas_cli.entities import month_window
from atlas_cli.main import app
from atlas_cli.recharges import (
    FACE_VALUES,
    FACE_WEIGHTS,
    SALARY_DAYS,
    daily_counts,
    seasonality_weight,
    subscriber_pool,
)
from atlas_cli.reference import load_municipalities
from typer.testing import CliRunner

REPO = Path(__file__).resolve().parents[2]
REFERENCE = REPO / "data" / "reference" / "municipalities_ibge.csv"
SP = ZoneInfo("America/Sao_Paulo")
ROWS = 60_000
runner = CliRunner()


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("gen")
    result = runner.invoke(
        app,
        [
            "generate", "--rows", str(ROWS), "--pos", "1500", "--distributors", "40",
            "--months", "2", "--end-month", "2026-11", "--scenarios", "none",
            "--out", str(out),
        ],
        env={"ATLAS_REFERENCE_PATH": str(REFERENCE)},
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    return out


def _recharges(out: Path):  # type: ignore[no-untyped-def]
    return ds.dataset(out / "recharges", format="parquet", partitioning="hive").to_table()


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def test_daily_counts_sum_exactly() -> None:
    days = _days(date(2026, 1, 1), date(2026, 3, 31))
    counts = daily_counts(1_001, days)
    assert sum(counts) == 1_001
    assert all(c >= 0 for c in counts)


def test_daily_counts_ratios_match_factors() -> None:
    days = _days(date(2026, 12, 1), date(2027, 2, 28))
    counts = dict(zip(days, daily_counts(5_000_000, days), strict=True))
    assert sum(counts.values()) == 5_000_000
    # Terça sem salário: dezembro (1,25) contra fevereiro (0,92).
    ratio_dec_feb = counts[date(2026, 12, 15)] / counts[date(2027, 2, 16)]
    assert ratio_dec_feb == pytest.approx(1.25 / 0.92, rel=1e-3)
    # Salário: terça dia 9 contra terça dia 16 no mesmo mês.
    assert counts[date(2026, 12, 8)] / counts[date(2026, 12, 15)] == pytest.approx(1.18, rel=1e-3)
    # Domingo contra segunda sem salário, em dezembro.
    assert counts[date(2026, 12, 20)] / counts[date(2026, 12, 21)] == pytest.approx(0.70, rel=1e-3)


def test_daily_counts_rejects_empty_window() -> None:
    with pytest.raises(ValueError):
        daily_counts(10, [])


def test_seasonality_factors_multiply() -> None:
    assert seasonality_weight(date(2026, 6, 15)) == 1.0  # segunda, sem fator
    assert seasonality_weight(date(2026, 12, 7)) == pytest.approx(1.18 * 1.25)  # segunda, salário
    assert seasonality_weight(date(2026, 12, 6)) == pytest.approx(1.18 * 1.25 * 0.70)  # domingo
    assert seasonality_weight(date(2026, 2, 3)) == pytest.approx(0.92)


def test_salary_days_have_above_average_volume(generated: Path) -> None:
    t = _recharges(generated)
    per_day = Counter(str(d) for d in t["dt"].to_pylist())
    salary: list[int] = []
    others: list[int] = []
    for iso, n in per_day.items():
        day = date.fromisoformat(iso)
        if day.weekday() == 6:
            continue  # domingo é outro efeito
        (salary if day.day in SALARY_DAYS else others).append(n)
    mean_salary = sum(salary) / len(salary)
    mean_others = sum(others) / len(others)
    assert mean_salary > mean_others * 1.10  # esperado ~ +18%


def test_sunday_has_below_average_volume(generated: Path) -> None:
    t = _recharges(generated)
    per_day = Counter(str(d) for d in t["dt"].to_pylist())
    sundays = [n for iso, n in per_day.items() if date.fromisoformat(iso).weekday() == 6]
    others = [n for iso, n in per_day.items() if date.fromisoformat(iso).weekday() != 6]
    assert sum(sundays) / len(sundays) < sum(others) / len(others) * 0.85


def test_invariant_5_row_count_within_one_percent(generated: Path) -> None:
    assert abs(_recharges(generated).num_rows - ROWS) <= ROWS * 0.01


def test_invariant_2_clean_data_without_scenarios(generated: Path) -> None:
    t = _recharges(generated)
    pos_ids = set(ds.dataset(generated / "pos", format="parquet").to_table()["pos_id"].to_pylist())
    for col in t.column_names:
        assert t[col].null_count == 0, col
    assert pc.count_distinct(t["recharge_id"]).as_py() == t.num_rows
    assert set(t["pos_id"].to_pylist()) <= pos_ids
    faces = {Decimal(v) for v in FACE_VALUES}
    assert set(t["amount_brl"].to_pylist()) <= faces
    assert set(t["status"].to_pylist()) == {"approved", "reversed"}


def test_partition_is_sao_paulo_day(generated: Path) -> None:
    t = _recharges(generated)
    for ts, dt in zip(t["recharge_ts_utc"].to_pylist(), t["dt"].to_pylist(), strict=True):
        assert ts.astimezone(SP).date().isoformat() == str(dt)


def test_status_and_face_value_proportions(generated: Path) -> None:
    t = _recharges(generated)
    n = t.num_rows
    reversed_share = t["status"].to_pylist().count("reversed") / n
    assert 0.010 < reversed_share < 0.020
    faces = Counter(int(v) for v in t["amount_brl"].to_pylist())
    for face, weight in zip(FACE_VALUES, FACE_WEIGHTS, strict=True):
        assert abs(faces[face] / n - weight) < 0.01, face


def test_intraday_curve_peaks_in_local_time(generated: Path) -> None:
    t = _recharges(generated)
    hours = Counter(ts.astimezone(SP).hour for ts in t["recharge_ts_utc"].to_pylist())
    peak = hours[12] + hours[19]
    assert peak > 2 * (hours[3] + hours[4])
    assert hours[12] > hours[8] and hours[19] > hours[15]


def test_acre_uses_local_hour_not_sao_paulo(generated: Path) -> None:
    municipalities = load_municipalities(REFERENCE)
    pos = ds.dataset(generated / "pos", format="parquet").to_table().to_pylist()
    index = dict(zip(municipalities.code, municipalities.uf, strict=True))
    acre = {p["pos_id"] for p in pos if index[p["municipality_ibge_code"]] == "AC"}
    t = _recharges(generated)
    rows = [r for r in t.select(["pos_id", "recharge_ts_utc"]).to_pylist() if r["pos_id"] in acre]
    assert rows
    hours = Counter(
        r["recharge_ts_utc"].astimezone(ZoneInfo("America/Rio_Branco")).hour for r in rows
    )
    assert hours[12] > hours[4]  # o pico segue o relógio do Acre


def test_only_active_pos_recharge(generated: Path) -> None:
    pos = {
        p["pos_id"]: p
        for p in ds.dataset(generated / "pos", format="parquet").to_table().to_pylist()
    }
    for r in _recharges(generated).select(["pos_id", "dt"]).to_pylist():
        p = pos[r["pos_id"]]
        day = date.fromisoformat(str(r["dt"]))
        assert p["opened_date"] <= day
        assert p["closed_date"] is None or p["closed_date"] >= day


def test_ingested_at_is_0900_utc_of_next_day(generated: Path) -> None:
    t = _recharges(generated)
    for ing, dt in zip(t["ingested_at_utc"].to_pylist(), t["dt"].to_pylist(), strict=True):
        expected = datetime.combine(date.fromisoformat(str(dt)) + timedelta(days=1), time(9), UTC)
        assert ing == expected


def test_same_seed_same_bytes(tmp_path: Path) -> None:
    def run(out: Path) -> dict[str, bytes]:
        result = runner.invoke(
            app,
            ["generate", "--rows", "2000", "--pos", "100", "--distributors", "5",
             "--months", "1", "--end-month", "2026-11", "--out", str(out)],
            env={"ATLAS_REFERENCE_PATH": str(REFERENCE)},
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        return {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*.parquet")}

    assert run(tmp_path / "a") == run(tmp_path / "b")


@pytest.mark.parametrize("rows", ["999", "10000001"])
def test_rows_out_of_range_exits_2(rows: str) -> None:
    assert runner.invoke(app, ["generate", "--rows", rows]).exit_code == 2


def test_unknown_scenario_exits_2() -> None:
    assert runner.invoke(app, ["generate", "--scenarios", "bogus"]).exit_code == 2


def test_window_matches_month_window(generated: Path) -> None:
    window = month_window(date(2026, 11, 1), 2)
    dts = sorted({str(d) for d in _recharges(generated)["dt"].to_pylist()})
    assert dts[0] == window.start.isoformat() and dts[-1] == window.end.isoformat()


def test_subscriber_pool_is_unique_and_seed_dependent() -> None:
    pool = subscriber_pool(42)
    assert len(set(pool)) == len(pool)
    assert all(v.startswith("SUB-") and len(v) == 14 for v in pool[:100])
    assert not set(pool) & set(subscriber_pool(43))
