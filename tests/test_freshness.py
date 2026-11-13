"""Checks da task de frescor do `atlas_daily` (SPEC-002 §4, task P6.7). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("freshness", ROOT / "pipeline" / "freshness.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["freshness"] = module
    spec.loader.exec_module(module)
    return module


fr = _load()
TODAY = date(2026, 11, 13)


def test_fresh_when_gold_reaches_d_minus_1() -> None:
    assert fr.freshness_status(date(2026, 11, 12), TODAY) == "fresh"
    assert fr.freshness_status(date(2026, 11, 13), TODAY) == "fresh"


def test_stale_when_older_than_d_minus_1_or_empty() -> None:
    assert fr.freshness_status(date(2026, 11, 11), TODAY) == "stale"
    assert fr.freshness_status(None, TODAY) == "stale"


def test_degraded_only_above_one_percent() -> None:
    assert fr.quality_status(fr.dropped_ratio(1000, 10)) == "ok"
    assert fr.quality_status(fr.dropped_ratio(1000, 11)) == "degraded"
    assert fr.quality_status(fr.dropped_ratio(0, 0)) == "ok"


def test_catalog_is_validated() -> None:
    assert fr.check_catalog("atlas_dev") == "atlas_dev"
    with pytest.raises(ValueError):
        fr.check_catalog("atlas; DROP")


def test_job_in_bundle_runs_at_6_sao_paulo_and_checks_after_refresh() -> None:
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    job = bundle["resources"]["jobs"]["atlas_daily"]
    assert job["schedule"]["quartz_cron_expression"] == "0 0 6 * * ?"
    assert job["schedule"]["timezone_id"] == "America/Sao_Paulo"
    assert job["timeout_seconds"] <= 120 * 60  # 06:00 + 2 h = 08:00
    tasks = {t["task_key"]: t for t in job["tasks"]}
    assert "pipeline_task" in tasks["refresh_pipeline"]
    assert tasks["check_freshness"]["depends_on"] == [{"task_key": "refresh_pipeline"}]
    assert job["email_notifications"]["on_failure"]


def test_check_script_finds_the_dev_prefixed_job() -> None:
    spec = importlib.util.spec_from_file_location(
        "check_atlas_daily", ROOT / "scripts" / "check_atlas_daily.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_atlas_daily"] = module
    spec.loader.exec_module(module)
    jobs = [
        {"job_id": 1, "settings": {"name": "[dev fulano] atlas_daily"}},
        {"job_id": 2, "settings": {"name": "outro_job"}},
        {"job_id": 3, "settings": {"name": "not_atlas_daily"}},
    ]
    assert module.matching_job_ids(jobs) == [1]
    assert module.matching_job_ids([{"job_id": 9, "settings": {"name": "atlas_daily"}}]) == [9]
