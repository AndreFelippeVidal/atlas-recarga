"""Check da reconciliação (task P8.4): a lógica de decisão com `_run` simulado. Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))  # o script importa o irmão check_commission_draft
_spec = importlib.util.spec_from_file_location(
    "check_commission_reconciliation", ROOT / "scripts" / "check_commission_reconciliation.py"
)
assert _spec is not None
assert _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
sys.modules["check_commission_reconciliation"] = check
_spec.loader.exec_module(check)

BATCH = "COM-2026-10-v1"


def _fake(monkeypatch: pytest.MonkeyPatch, recon: list[list[str | None]], count: str) -> None:
    def run(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
        return recon if "reconciliation" in statement else [[count]]

    monkeypatch.setattr(check, "_run", run)


def _row(status: str = "passed", diff: str = "0.00") -> list[str | None]:
    return [status, "4798", diff, "0.00", "0.00", "0.00"]


def test_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, [_row()], "4798")
    out = check.check("p", "w", "atlas_dev", BATCH)
    assert not any(line.startswith("FALHA") for line in out)


@pytest.mark.parametrize(
    ("recon", "count"),
    [([_row("failed")], "4798"), ([_row(diff="0.01")], "4798"), ([_row()], "4000"), ([], "4798")],
)
def test_failures(
    monkeypatch: pytest.MonkeyPatch, recon: list[list[str | None]], count: str
) -> None:
    _fake(monkeypatch, recon, count)
    out = check.check("p", "w", "atlas_dev", BATCH)
    assert any(line.startswith("FALHA") for line in out)


def test_rejects_bad_batch_id() -> None:
    with pytest.raises(ValueError):
        check.check("p", "w", "atlas_dev", "x'; DROP")
