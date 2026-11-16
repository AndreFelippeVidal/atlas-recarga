"""Check do relatório `commission_review` (task P8.8). Sem workspace: `_run` é trocado."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_commission_review", ROOT / "scripts" / "check_commission_review.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load()
BATCH = "COM-2026-10-v1"


def _fake(previous: str | None, top_amounts: list[str]):  # type: ignore[no-untyped-def]
    def run(profile: str, wh: str, catalog: str, statement: str) -> list[list[str | None]]:
        assert catalog == "atlas_dev" and "INSERT" not in statement.upper()
        if "total_pos_brl, total_distributor_brl, pos_lines" in statement:
            return [["10.00", "5.00", "2", "1", "1", "passed"]]
        if "COALESCE(SUM(CASE" in statement:
            return [["10.00", "5.00", "2", "1", "1"]]
        if "rnk, commission_brl" in statement:
            return [[str(n + 1), a] for n, a in enumerate(top_amounts)]
        if "SELECT COUNT(*) FROM (" in statement and "previous_commission_brl" in statement:
            return [["3" if previous else "0"]]
        if "SELECT COUNT(*)" in statement:
            return [["1"]]
        if "SELECT flag, lines" in statement:
            return [["spike_3x", "1"]]
        if "SELECT previous_batch_id" in statement:
            return [[previous]]
        if "add_months(reference_month, 1)" in statement:
            return [["locked", "2026-09-01", "2026-10-01"]]
        if "SELECT reference_month FROM batches" in statement:
            return [["2026-10-01"]]
        raise AssertionError(statement)

    return run


def test_passes_with_a_previous_locked_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    # 3 linhas no lote (2 PDV + 1 distribuidor), então o top 20 tem 3 linhas
    monkeypatch.setattr(check, "_run", _fake("COM-2026-09-v1", ["9.00", "5.00", "1.00"]))
    out = check.check("p", "w", "atlas_dev", BATCH)
    assert not [line for line in out if line.startswith("FALHA")], out


def test_passes_without_a_previous_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "_run", _fake(None, ["9.00", "5.00", "1.00"]))
    out = check.check("p", "w", "atlas_dev", BATCH)
    assert not [line for line in out if line.startswith("FALHA")], out
    assert any("sem lote locked" in line for line in out)


def test_fails_when_top20_is_not_sorted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "_run", _fake(None, ["1.00", "5.00", "9.00"]))
    assert any(line.startswith("FALHA") for line in check.check("p", "w", "atlas_dev", BATCH))


def test_rejects_a_bad_batch_id() -> None:
    with pytest.raises(ValueError, match="batch_id inválido"):
        check.check("p", "w", "atlas_dev", "x'; DROP TABLE y; --")


def test_reports_a_workspace_error_as_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object) -> list[list[str | None]]:
        raise RuntimeError("sem acesso")

    monkeypatch.setattr(check, "_run", boom)
    (line,) = check.check("p", "w", "atlas_dev", BATCH)
    assert line.startswith("FALHA") and "sem acesso" in line
