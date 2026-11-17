"""Lógica pura de `scripts/setup_agent_trace_tables.py` (P10.5). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "setup_agent_trace_tables", ROOT / "scripts" / "setup_agent_trace_tables.py"
)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
sys.modules["setup_agent_trace_tables"] = mod
_spec.loader.exec_module(mod)

SP = "1fdebf2b-83f2-4685-af7f-31f7b2e89a46"


def test_grants_are_minimal_and_per_object() -> None:
    stmts = mod.grant_statements(
        "atlas_dev", SP, [("agent_otel_spans", "MANAGED"), ("agent_otel_logs", "MANAGED")]
    )
    assert stmts[0].startswith("GRANT USE CATALOG") and stmts[1].startswith("GRANT USE SCHEMA")
    assert all("SELECT, MODIFY ON atlas_dev.observability.agent_" in s for s in stmts[2:])
    assert not any("ALL PRIVILEGES" in s or ("ON SCHEMA" in s and "SELECT" in s) for s in stmts)


def test_a_view_only_gets_select() -> None:
    # MODIFY não vale para view (erro visto no dev com agent_trace_metadata)
    stmts = mod.grant_statements("atlas_dev", SP, [("agent_trace_metadata", "VIEW")])
    assert stmts[-1] == f"GRANT SELECT ON atlas_dev.observability.agent_trace_metadata TO `{SP}`"


@pytest.mark.parametrize(
    ("catalog", "principal", "tables"),
    [
        ("atlas; DROP", SP, []),
        ("atlas_dev", "x`; DROP", []),
        ("atlas_dev", SP, [("pipeline_freshness", "MANAGED")]),
        ("atlas_dev", SP, [("agent_x; DROP TABLE y", "MANAGED")]),
    ],
)
def test_bad_input_is_rejected(catalog: str, principal: str, tables: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError):
        mod.grant_statements(catalog, principal, tables)


def test_dry_run_changes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    code = mod.main(
        [
            "--profile",
            "p",
            "--catalog",
            "atlas_dev",
            "--warehouse-id",
            "w",
            "--experiment-id",
            "1",
            "--app-sp",
            SP,
        ]
    )
    assert code == 0
    assert "dry-run" in capsys.readouterr().out
