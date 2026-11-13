"""Checks of `scripts/setup_workspace.py` (SPEC-002 §2, task P5.2). No workspace needed."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "setup_workspace", ROOT / "scripts" / "setup_workspace.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["setup_workspace"] = module
    spec.loader.exec_module(module)
    return module


setup = _load()


def test_statements_are_idempotent() -> None:
    statements = setup.build_statements("atlas_dev")
    assert statements[0] == "CREATE CATALOG IF NOT EXISTS atlas_dev"
    assert all("IF NOT EXISTS" in s for s in statements)


def test_creates_every_adr_0003_schema_and_the_landing_volume() -> None:
    statements = setup.build_statements("atlas")
    for schema in ("raw", "bronze", "silver", "gold", "semantic", "commission", "eval",
                   "observability"):  # fmt: skip
        assert f"CREATE SCHEMA IF NOT EXISTS atlas.{schema}" in statements
    assert any(s.startswith("CREATE VOLUME IF NOT EXISTS atlas.raw.landing") for s in statements)


@pytest.mark.parametrize("bad", ["", "Atlas", "atlas; DROP CATALOG x", "a-b", "1atlas", "a b"])
def test_rejects_unsafe_catalog_names(bad: str) -> None:
    with pytest.raises(ValueError):
        setup.build_statements(bad)


def test_groups_are_the_ones_the_specs_name() -> None:
    assert set(setup.GROUPS) == {
        "atlas_readers",
        "atlas_commission_analysts",
        "atlas_commission_directors",
    }


def test_targets_match_databricks_yml() -> None:
    text = (ROOT / "databricks.yml").read_text(encoding="utf-8")
    for target, catalog in setup.CATALOGS.items():
        block = re.search(rf"^  {target}:\n(?:    .*\n|\n)+", text, re.MULTILINE)
        assert block, target
        assert f"catalog: {catalog}" in block.group(0)


def test_dry_run_changes_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert setup.main(["--target", "dev", "--profile", "x", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "CREATE CATALOG IF NOT EXISTS atlas_dev;" in out
    assert "atlas_readers" in out


def test_ensure_groups_creates_only_missing_and_tolerates_already_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_cli(profile: str, args: list[str], body: object = None) -> object:
        if args[:2] == ["groups", "list"]:
            return [{"displayName": "atlas_readers"}]
        assert isinstance(body, dict)
        name = str(body["displayName"])
        calls.append(name)
        if name == "atlas_commission_directors":
            raise RuntimeError("Group with name atlas_commission_directors already exists")
        return {}

    monkeypatch.setattr(setup, "_cli", fake_cli)
    assert setup._ensure_groups("p") == ["atlas_commission_analysts"]
    assert "atlas_readers" not in calls


def test_run_sql_gives_up_on_a_stuck_statement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup, "_cli", lambda *a, **k: {"status": {"state": "RUNNING"},
                                                        "statement_id": "s"})  # fmt: skip
    monkeypatch.setattr(setup.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError):
        setup._run_sql("p", "w", "SELECT 1")


@pytest.mark.parametrize("message", ["already in use", "Conflict: group exists"])
def test_ensure_groups_tolerates_other_conflict_messages(
    monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    def fake_cli(profile: str, args: list[str], body: object = None) -> object:
        if args[:2] == ["groups", "list"]:
            return []
        raise RuntimeError(message)

    monkeypatch.setattr(setup, "_cli", fake_cli)
    assert setup._ensure_groups("p") == []


def test_ensure_groups_reraises_other_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_cli(profile: str, args: list[str], body: object = None) -> object:
        if args[:2] == ["groups", "list"]:
            return []
        raise RuntimeError("permission denied")

    monkeypatch.setattr(setup, "_cli", fake_cli)
    with pytest.raises(RuntimeError, match="permission denied"):
        setup._ensure_groups("p")


def test_run_sql_succeeds_after_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter(
        [
            {"statement_id": "s", "status": {"state": "RUNNING"}},
            {"statement_id": "s", "status": {"state": "SUCCEEDED"}},
        ]
    )
    monkeypatch.setattr(setup, "_cli", lambda *a, **k: next(responses))
    monkeypatch.setattr(setup.time, "sleep", lambda _s: None)
    setup._run_sql("p", "w", "SELECT 1")


def test_run_sql_timeout_message_says_it_may_still_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        setup, "_cli", lambda *a, **k: {"statement_id": "s", "status": {"state": "RUNNING"}}
    )
    monkeypatch.setattr(setup.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="may still finish"):
        setup._run_sql("p", "w", "SELECT 1")


def test_pick_warehouse(monkeypatch: pytest.MonkeyPatch) -> None:
    assert setup._pick_warehouse("p", "given") == "given"
    monkeypatch.setattr(setup, "_cli", lambda *a, **k: [{"id": "w1"}])
    assert setup._pick_warehouse("p", None) == "w1"
    monkeypatch.setattr(setup, "_cli", lambda *a, **k: [{"id": "w1"}, {"id": "w2"}])
    with pytest.raises(RuntimeError, match="--warehouse-id"):
        setup._pick_warehouse("p", None)


def test_main_runs_every_statement_then_groups(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []
    monkeypatch.setattr(setup, "_run_sql", lambda _p, _w, statement: ran.append(statement))
    monkeypatch.setattr(setup, "_ensure_groups", lambda _p: ["atlas_readers"])
    assert setup.main(["--target", "demo", "--profile", "x", "--warehouse-id", "w"]) == 0
    assert ran == setup.build_statements("atlas") + setup.build_grant_statements("atlas")
    assert "groups created: atlas_readers" in capsys.readouterr().out


def test_readers_get_select_only_on_semantic() -> None:
    grants = setup.build_grant_statements("atlas_dev")
    assert grants == [
        "GRANT USE CATALOG ON CATALOG atlas_dev TO `atlas_readers`",
        "GRANT USE SCHEMA, SELECT ON SCHEMA atlas_dev.semantic TO `atlas_readers`",
    ]
    for layer in ("raw", "bronze", "silver", "gold", "commission", "eval", "observability"):
        assert not any(f"atlas_dev.{layer}" in g for g in grants)


def test_grants_reject_unsafe_catalog_names() -> None:
    with pytest.raises(ValueError):
        setup.build_grant_statements("atlas; DROP CATALOG x")


def test_dry_run_lists_the_grants(capsys: pytest.CaptureFixture[str]) -> None:
    assert setup.main(["--target", "dev", "--profile", "x", "--dry-run"]) == 0
    assert "GRANT USE SCHEMA, SELECT ON SCHEMA atlas_dev.semantic" in capsys.readouterr().out
