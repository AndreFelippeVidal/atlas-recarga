"""`scripts/load_data.py` (P14.1, SPEC-012). Sem workspace: upload e `bundle run` são simulados."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import load_data as ld  # noqa: E402

SMALL = ["--rows", "20000", "--base-months", "2", "--base-end-month", "2026-11"]


def _args(tmp_path: Path, *extra: str) -> list[str]:
    return ["--profile", "p", "--out", str(tmp_path / "out"), *SMALL, *extra]


class Recorder:
    """Roda o atlas-cli de verdade e só registra o upload e o `bundle run`."""

    def __init__(self, pipeline_code: int = 0, upload_code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.pipeline_code, self.upload_code = pipeline_code, upload_code

    def __call__(self, command: list[str]) -> int:
        self.calls.append(command)
        if command[0] == "databricks":
            return self.pipeline_code
        if "upload" in command:
            return self.upload_code
        return subprocess.run(command, check=False, cwd=ROOT).returncode  # noqa: S603

    def names(self) -> list[str]:
        return [
            "pipeline" if c[0] == "databricks" else next(w for w in c[1:] if not w.startswith("-"))
            for c in self.calls
        ]


def test_plan_separates_days_outside_the_base_window() -> None:
    plan = ld.build_plan(date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 1), 12)
    assert (plan.base_first, plan.base_last) == (date(2025, 11, 1), date(2026, 10, 31))
    assert plan.outside == (date(2026, 11, 1), date(2026, 11, 2))
    assert plan.days == 4


def test_plan_inside_the_window_has_no_outside_days() -> None:
    plan = ld.build_plan(date(2026, 8, 1), date(2026, 8, 31), date(2026, 11, 1), 12)
    assert plan.outside == ()


@pytest.mark.parametrize(
    ("first", "last"),
    [(date(2026, 8, 5), date(2026, 8, 4)), (date(2025, 1, 1), date(2026, 1, 2))],
)
def test_plan_rejects_inverted_or_too_long_range(first: date, last: date) -> None:
    with pytest.raises(ld.LoadError) as error:
        ld.build_plan(first, last, date(2026, 11, 1), 12)
    assert error.value.code == ld.EXIT_INVALID


@pytest.mark.parametrize("value", ["2026-13-01", "26-10-01", "x"])
def test_parse_day_rejects_bad_dates(value: str) -> None:
    with pytest.raises(ld.LoadError):
        ld.parse_day(value)


def test_dry_run_prints_the_plan_and_runs_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    recorder = Recorder()
    code = ld.main(
        ["--from", "2026-10-30", "--to", "2026-11-02", *_args(tmp_path), "--dry-run"], run=recorder
    )
    out = capsys.readouterr().out
    assert code == 0 and recorder.calls == []
    assert "dias fora da janela base (--incremental-day): 2" in out
    assert "/Volumes/atlas_dev/raw/landing/" in out
    assert not (tmp_path / "out").exists()


def test_demo_target_uses_the_demo_volume(capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["--from", "2026-08-01", "--to", "2026-08-02", "--profile", "p", "--target", "demo"]
    ld.main([*argv, "--dry-run"])
    assert "/Volumes/atlas/raw/landing/" in capsys.readouterr().out


def test_entity_mismatches() -> None:
    local = {
        "files": {
            "pos/pos.parquet": {"sha256": "a"},
            "distributors/distributors.parquet": {"sha256": "b"},
        }
    }
    same = json.dumps(local)
    other = json.dumps(
        {
            "files": {
                "pos/pos.parquet": {"sha256": "x"},
                "distributors/distributors.parquet": {"sha256": "b"},
            }
        }
    )
    assert ld.entity_mismatches(local, None) == []
    assert ld.entity_mismatches(local, same) == []
    assert ld.entity_mismatches(local, other) == ["pos/pos.parquet"]
    assert ld.entity_mismatches(local, "{não é json") == []
    assert ld.entity_mismatches(local, json.dumps({"files": {}})) == []


def test_reset_out_refuses_a_folder_that_is_not_a_generated_output(tmp_path: Path) -> None:
    (tmp_path / "x.txt").write_text("meu arquivo")
    with pytest.raises(ld.LoadError) as error:
        ld.reset_out(tmp_path)
    assert error.value.code == ld.EXIT_INVALID and (tmp_path / "x.txt").exists()


def test_end_to_end_inside_and_outside_the_base_window(tmp_path: Path) -> None:
    recorder = Recorder()
    code = ld.main(
        ["--from", "2026-10-29", "--to", "2026-11-02", *_args(tmp_path)],
        run=recorder,
        volume_factory=lambda profile: _Volume(None),
    )
    assert code == 0
    assert recorder.names() == ["generate"] + ["generate"] * 2 + ["validate", "upload", "pipeline"]
    out = tmp_path / "out"
    days = sorted(p.name.removeprefix("dt=") for p in (out / "recharges").glob("dt=*"))
    assert days == ["2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"]
    manifest = json.loads((out / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["pruned"] == {"from": "2026-10-29", "to": "2026-11-02"}
    upload = next(c for c in recorder.calls if "upload" in c)
    assert upload[upload.index("--dest") + 1] == "/Volumes/atlas_dev/raw/landing/"
    assert recorder.calls[-1][:4] == ["databricks", "bundle", "run", "atlas_daily"]


def test_rerun_with_the_same_range_regenerates_cleanly(tmp_path: Path) -> None:
    argv = ["--from", "2026-10-29", "--to", "2026-10-30", *_args(tmp_path), "--no-run"]
    for _ in range(2):
        assert ld.main(argv, run=Recorder(), volume_factory=lambda p: _Volume(None)) == 0


def test_no_run_skips_the_pipeline(tmp_path: Path) -> None:
    recorder = Recorder()
    code = ld.main(
        ["--from", "2026-10-29", "--to", "2026-10-30", *_args(tmp_path), "--no-run"],
        run=recorder,
        volume_factory=lambda p: _Volume(None),
    )
    assert code == 0 and "pipeline" not in recorder.names()


class _Volume:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def read_text(self, path: str) -> str | None:
        assert path == "/Volumes/atlas_dev/raw/landing/_manifest.json"
        return self.text


def test_different_pos_already_in_the_landing_aborts_before_upload(tmp_path: Path) -> None:
    remote = json.dumps({"files": {"pos/pos.parquet": {"sha256": "outro"}}})
    recorder = Recorder()
    code = ld.main(
        ["--from", "2026-10-29", "--to", "2026-10-30", *_args(tmp_path)],
        run=recorder,
        volume_factory=lambda p: _Volume(remote),
    )
    assert code == ld.EXIT_INVALID
    assert "upload" not in recorder.names() and "pipeline" not in recorder.names()


@pytest.mark.parametrize(
    ("kwargs", "code", "last_step"),
    [
        ({"upload_code": 1}, ld.EXIT_UPLOAD, "upload"),
        ({"pipeline_code": 1}, ld.EXIT_PIPELINE, "pipeline"),
    ],
)
def test_failures_map_to_exit_codes(
    tmp_path: Path, kwargs: dict[str, Any], code: int, last_step: str
) -> None:
    recorder = Recorder(**kwargs)
    result = ld.main(
        ["--from", "2026-10-29", "--to", "2026-10-30", *_args(tmp_path)],
        run=recorder,
        volume_factory=lambda p: _Volume(None),
    )
    assert result == code and recorder.names()[-1] == last_step


def test_days_before_the_base_window_come_from_incremental_days(tmp_path: Path) -> None:
    recorder = Recorder()
    code = ld.main(
        ["--from", "2026-08-01", "--to", "2026-08-02", *_args(tmp_path), "--no-run"],
        run=recorder,
        volume_factory=lambda p: _Volume(None),
    )
    assert code == 0
    assert recorder.names() == ["generate", "generate", "generate", "validate", "upload"]
    days = sorted(p.name for p in (tmp_path / "out" / "recharges").glob("dt=*"))
    assert days == ["dt=2026-08-01", "dt=2026-08-02"]
