import json
import shutil
from datetime import date
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from atlas_cli.entities import month_window
from atlas_cli.exit_codes import ExitCode
from atlas_cli.incremental import day_volume
from atlas_cli.main import app
from atlas_cli.manifest import MANIFEST_NAME, sha256_file
from atlas_cli.recharges import iter_days
from typer.testing import CliRunner, Result

REPO = Path(__file__).resolve().parents[2]
ENV = {"ATLAS_REFERENCE_PATH": str(REPO / "data" / "reference" / "municipalities_ibge.csv")}
runner = CliRunner()
DAY = "2026-11-10"


def _base(out: Path, scenarios: str = "none", fmt: str = "parquet") -> None:
    result = runner.invoke(
        app,
        [
            "generate",
            *("--rows", "20000"),
            *("--pos", "800"),
            *("--months", "2"),
            *("--end-month", "2026-11"),
            *("--scenarios", scenarios),
            *("--format", fmt),
            *("--out", str(out)),
        ],
        env=ENV,
    )
    assert result.exit_code == 0, result.output


def _incremental(out: Path, *extra: str, day: str = DAY, scenarios: str = "none") -> Result:
    return runner.invoke(
        app,
        [
            "generate",
            *("--rows", "20000"),
            *("--scenarios", scenarios),
            *("--incremental-day", day),
            *("--out", str(out)),
            *extra,
        ],
        env=ENV,
    )


def _tree(out: Path) -> dict[str, str]:
    return {
        p.relative_to(out).as_posix(): sha256_file(p)
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.name != MANIFEST_NAME
    }


def test_only_the_day_partition_is_generated(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    before = _tree(out)
    result = _incremental(out)
    assert result.exit_code == 0, result.output
    after = _tree(out)
    added = set(after) - set(before)
    assert added == {f"recharges/dt={DAY}/part-0000.parquet"}
    assert {k for k in before if after[k] != before[k]} == set()  # nada mais mudou


def test_pos_ids_are_coherent_with_existing_pos(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    assert _incremental(out).exit_code == 0
    table = pq.read_table(out / "recharges" / f"dt={DAY}" / "part-0000.parquet")
    pos = pq.read_table(out / "pos" / "pos.parquet")
    assert table.num_rows > 0
    assert pc.all(pc.is_in(table["pos_id"], value_set=pos["pos_id"])).as_py()


def test_manifest_updated_and_validate_passes(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    assert _incremental(out).exit_code == 0
    manifest = json.loads((out / MANIFEST_NAME).read_text())
    rel = f"recharges/dt={DAY}/part-0000.parquet"
    assert manifest["files"][rel]["sha256"] == sha256_file(out / rel)
    assert manifest["incremental"][DAY]["rows"] == manifest["incremental"][DAY]["rows"] > 0
    validated = runner.invoke(app, ["validate", "--out", str(out)], env=ENV)
    assert validated.exit_code == 0, validated.output
    assert "[pulado] invariante 5" in validated.output


def test_regenerating_is_deterministic_and_replaces(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    assert _incremental(out).exit_code == 0
    first, manifest = _tree(out), (out / MANIFEST_NAME).read_text()
    again = _incremental(out)
    assert again.exit_code == 0 and "substituída" in again.output
    assert _tree(out) == first
    assert (out / MANIFEST_NAME).read_text() == manifest


def test_day_outside_history_is_accepted(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    result = _incremental(out, day="2027-03-02")
    assert result.exit_code == 0, result.output
    assert (out / "recharges" / "dt=2027-03-02" / "part-0000.parquet").is_file()
    assert runner.invoke(app, ["validate", "--out", str(out)], env=ENV).exit_code == 0


def test_replacing_a_historical_partition_keeps_counts_consistent(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out, scenarios="all")
    result = _incremental(out, day="2026-10-15", scenarios="all")
    assert result.exit_code == 0, result.output
    validated = runner.invoke(app, ["validate", "--out", str(out)], env=ENV)
    assert validated.exit_code == 0, validated.output


def test_scenarios_apply_to_the_day(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    assert _incremental(out, scenarios="unknown_pos").exit_code == 0
    manifest = json.loads((out / MANIFEST_NAME).read_text())
    assert manifest["incremental"][DAY]["scenarios"]["unknown_pos"]["rows"] >= 1
    # o invariante 2 só vale sem cenários, nem no incremental
    assert runner.invoke(app, ["validate", "--out", str(out)], env=ENV).exit_code == 0


def test_csv_format(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out, fmt="csv")
    result = _incremental(out, "--format", "csv")
    assert result.exit_code == 0, result.output
    assert (out / "recharges" / f"dt={DAY}" / "part-0000.csv").is_file()
    assert runner.invoke(app, ["validate", "--out", str(out)], env=ENV).exit_code == 0


def test_ignored_flags_warn(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    result = _incremental(out, "--months", "6")
    assert result.exit_code == 0
    assert "--months" in result.output and "ignorado" in result.output


@pytest.mark.parametrize("day", ["2026-13-01", "10/11/2026", "2026-11-1", "abc"])
def test_invalid_day_is_invalid_flag(tmp_path: Path, day: str) -> None:
    out = tmp_path / "out"
    _base(out)
    assert _incremental(out, day=day).exit_code == ExitCode.INVALID_FLAG


def test_missing_manifest_is_invalid_flag(tmp_path: Path) -> None:
    result = _incremental(tmp_path / "vazio")
    assert result.exit_code == ExitCode.INVALID_FLAG


def test_missing_pos_is_invalid_flag(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    shutil.rmtree(out / "pos")
    assert _incremental(out).exit_code == ExitCode.INVALID_FLAG


def test_seed_mismatch_is_invalid_flag(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    assert _incremental(out, "--seed", "7").exit_code == ExitCode.INVALID_FLAG


def test_missing_reference_exits_3(tmp_path: Path) -> None:
    out = tmp_path / "out"
    _base(out)
    result = runner.invoke(
        app,
        ["generate", "--incremental-day", DAY, "--out", str(out)],
        env={"ATLAS_REFERENCE_PATH": str(tmp_path / "nao-existe.csv")},
    )
    assert result.exit_code == ExitCode.REFERENCE_DATA_INVALID


def test_day_volume_follows_seasonality() -> None:
    days = list(iter_days(month_window(date(2026, 11, 1), 2)))
    salary, sunday = date(2026, 10, 7), date(2026, 10, 18)
    assert day_volume(20_000, salary, days) > day_volume(20_000, sunday, days)
    assert sum(day_volume(20_000, d, days) for d in days) == pytest.approx(20_000, rel=0.01)
