"""Sync do golden set para o dataset MLflow (SPEC-008 §3, task P9.2). Sem workspace."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sync = _load("sync_golden_set", "eval/sync_golden_set.py")
CASES: list[dict[str, Any]] = sync.load_cases(ROOT / "eval" / "golden_set.yaml")


def test_dataset_name_per_catalog() -> None:
    assert sync.dataset_name("atlas") == "atlas.eval.agent_golden_set"
    assert sync.dataset_name("atlas_dev") == "atlas_dev.eval.agent_golden_set"
    with pytest.raises(ValueError):
        sync.dataset_name("atlas; DROP")


def test_one_record_per_case_without_computed_values() -> None:
    records = sync.to_records(CASES)
    assert len(records) == len(CASES) == 30
    for case, record in zip(CASES, records, strict=True):
        assert record["inputs"] == {"question": case["question"]}
        expectations = record["expectations"]
        assert expectations["id"] == case["id"]
        assert expectations["category"] == case["category"]
        assert "value" not in expectations  # guarda a SQL, nunca o número
        if case["category"] == "refusal":
            assert "reference_sql" not in expectations
        else:
            assert expectations["reference_sql"] == case["reference_sql"]
            assert expectations["expected_source_view"] == case["expected_source_view"]


def test_questions_are_unique_so_merge_does_not_collapse_cases() -> None:
    questions = [r["inputs"]["question"] for r in sync.to_records(CASES)]
    assert len(set(questions)) == len(questions)


@pytest.mark.parametrize(
    "bad",
    [
        {"category": "metric", "question": "q"},  # sem id
        {"id": "X", "category": "nope", "question": "q"},
        {"id": "X", "category": "metric", "question": " "},
    ],
)
def test_invalid_case_is_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        sync.to_records([bad])


def test_duplicate_id_is_rejected() -> None:
    case = {"id": "X", "category": "metric", "question": "q"}
    with pytest.raises(ValueError):
        sync.to_records([case, case])


def test_job_runs_the_sync_with_catalog_and_yaml() -> None:
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    job = bundle["resources"]["jobs"]["atlas_eval_sync"]
    task = job["tasks"][0]["spark_python_task"]
    assert task["python_file"] == "eval/sync_golden_set.py"
    assert task["parameters"] == ["${var.catalog}", "${workspace.file_path}/eval/golden_set.yaml"]
    deps = job["environments"][0]["spec"]["dependencies"]
    assert any(d.startswith("mlflow") for d in deps)


def test_check_counts() -> None:
    check = _load("check_agent_golden_set", "scripts/check_agent_golden_set.py")
    assert check.check_counts(30, 30, 1).startswith("ok")
    assert check.check_counts(30, 29, 1).startswith("FALHA")
    assert check.check_counts(30, 30, None).startswith("FALHA")
