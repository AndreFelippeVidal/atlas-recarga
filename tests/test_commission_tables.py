"""Checks do DDL de `commission.*` e do check de append-only (task P8.2). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
DDL = ROOT / "commission" / "ddl"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


apply_ddl = _load(ROOT / "commission" / "apply_ddl.py", "apply_ddl")
check = _load(ROOT / "scripts" / "check_commission_append_only.py", "check_commission_append_only")


def _sql(table: str) -> str:
    return (DDL / f"{table}.sql").read_text(encoding="utf-8")


def test_ddl_files_match_the_spec_tables() -> None:
    assert {p.stem for p in DDL.glob("*.sql")} == set(apply_ddl.TABLES)
    assert [name for name, _ in apply_ddl.load_definitions(DDL)] == list(apply_ddl.TABLES)


@pytest.mark.parametrize("table", apply_ddl.TABLES)
def test_append_only_exactly_on_the_two_audit_tables(table: str) -> None:
    has_property = "'delta.appendOnly' = 'true'" in _sql(table)
    assert has_property == (table in apply_ddl.APPEND_ONLY_TABLES)


def test_append_only_set_is_batch_events_and_locked_lines() -> None:
    assert {"batch_events", "locked_lines"} == apply_ddl.APPEND_ONLY_TABLES
    assert set(check.APPEND_ONLY) == apply_ddl.APPEND_ONLY_TABLES
    assert set(check.MUTABLE) == set(apply_ddl.TABLES) - apply_ddl.APPEND_ONLY_TABLES


@pytest.mark.parametrize("table", apply_ddl.TABLES)
def test_ddl_is_idempotent_and_qualified(table: str) -> None:
    ddl = apply_ddl.build_ddl("atlas_dev", table, _sql(table))
    assert ddl.startswith(f"CREATE TABLE IF NOT EXISTS atlas_dev.commission.{table} (")
    assert "${" not in ddl


@pytest.mark.parametrize("table", apply_ddl.TABLES)
def test_money_is_decimal_never_float(table: str) -> None:
    sql = _sql(table).upper()
    assert "DOUBLE" not in sql
    assert "FLOAT" not in sql
    for line in _sql(table).splitlines():
        if "_brl" in line:
            assert "DECIMAL(14,2)" in line


def test_batches_has_demo_mode_and_spec_columns() -> None:
    sql = _sql("batches")
    for column in (
        "batch_id",
        "reference_month",
        "version",
        "status",
        "total_pos_brl",
        "total_distributor_brl",
        "source_snapshot_version",
        "remittance_sha256",
        "demo_mode",
        "created_at_utc",
    ):
        assert f"  {column} " in sql


def test_locked_lines_mirror_batch_lines() -> None:
    def columns(table: str) -> list[str]:
        return [
            line.split()[0]
            for line in _sql(table).splitlines()
            if line.startswith("  ") and "COMMENT" in line
        ]

    assert columns("locked_lines") == columns("batch_lines")


def test_batch_events_columns() -> None:
    sql = _sql("batch_events")
    for column in (
        "event_id",
        "batch_id",
        "from_status",
        "to_status",
        "actor",
        "role",
        "justification",
        "event_ts_utc",
    ):
        assert f"  {column} " in sql


def test_every_table_and_column_has_a_comment() -> None:
    for table in apply_ddl.TABLES:
        for line in _sql(table).splitlines():
            if line.startswith("  "):
                assert "COMMENT" in line, f"{table}: {line.strip()}"
        assert "\nCOMMENT '" in _sql(table)


def test_apply_ddl_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="catalog"):
        apply_ddl.build_ddl("Atlas; DROP", "batches", _sql("batches"))
    with pytest.raises(ValueError, match="table"):
        apply_ddl.build_ddl("atlas_dev", "x; y", "SELECT 1")
    with pytest.raises(ValueError, match="placeholder"):
        apply_ddl.build_ddl("atlas_dev", "batches", "CREATE TABLE ${other}.x")
    with pytest.raises(ValueError, match="instrução"):
        apply_ddl.build_ddl("atlas_dev", "batches", "SELECT 1; SELECT 2")


def test_load_definitions_requires_all_tables(tmp_path: Path) -> None:
    (tmp_path / "batches.sql").write_text("SELECT 1")
    with pytest.raises(ValueError, match="esperado"):
        apply_ddl.load_definitions(tmp_path)


def test_check_helpers() -> None:
    assert check.is_append_only([["delta.appendOnly", "true"], ["x", "y"]])
    assert not check.is_append_only([["delta.appendOnly", "false"]])
    assert not check.is_append_only([])
    assert check.is_rejection("[DELTA_CANNOT_MODIFY_APPEND_ONLY] This table is configured")
    assert check.is_rejection("This table is configured to only allow appends.")
    assert not check.is_rejection("TABLE_OR_VIEW_NOT_FOUND")
    assert not check.is_rejection("PERMISSION_DENIED on delta.appendOnly property")


def test_append_only_alter_only_for_audit_tables() -> None:
    alter = apply_ddl.build_append_only_alter("atlas_dev", "locked_lines")
    assert alter.startswith("ALTER TABLE atlas_dev.commission.locked_lines SET TBLPROPERTIES")
    with pytest.raises(ValueError, match="append-only"):
        apply_ddl.build_append_only_alter("atlas_dev", "batches")


def test_probe_statements_are_scoped_and_append_only() -> None:
    statements = check.probe_statements("atlas_dev")
    assert "atlas_dev.commission._probe_append_only" in statements["create"]
    assert "'delta.appendOnly' = 'true'" in statements["create"]
    assert statements["update"].startswith("UPDATE atlas_dev.commission._probe")
    assert statements["delete"].startswith("DELETE FROM atlas_dev.commission._probe")
    assert statements["drop"].startswith("DROP TABLE IF EXISTS")


def test_bundle_declares_the_deploy_job_not_the_review_job() -> None:
    text = (ROOT / "databricks.yml").read_text(encoding="utf-8")
    assert "atlas_commission_deploy:" in text
    assert "commission/apply_ddl.py" in text
    assert "atlas_commission_review:" not in text
