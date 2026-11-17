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
    assert len(records) == len(CASES) == 31
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
        if case["category"] == "no_period":
            assert expectations["reference_month_sql"] == case["reference_month_sql"]


def test_reference_sql_points_to_the_target_catalog() -> None:
    dev = sync.to_records(CASES, "atlas_dev")
    for record in dev:
        for field in ("reference_sql", "reference_month_sql"):
            sql = record["expectations"].get(field)
            if sql:
                assert "atlas_dev.semantic." in sql
                assert "atlas.semantic." not in sql
    prod = sync.to_records(CASES, "atlas")
    assert prod[0]["expectations"]["reference_sql"] == CASES[0]["reference_sql"]


def test_required_fields_per_category() -> None:
    with pytest.raises(ValueError):
        sync.to_records([{"id": "X", "category": "refusal", "question": "q"}])
    with pytest.raises(ValueError):
        sync.to_records([{"id": "X", "category": "metric", "question": "q"}])
    metric = {
        "id": "X",
        "category": "metric",
        "question": "q",
        "reference_sql": "SELECT MEASURE(m) FROM atlas.semantic.mv_recharges",
        "expected_source_view": "mv_recharges",
    }
    with pytest.raises(ValueError, match="tolerance_pct"):
        sync.to_records([metric])
    with pytest.raises(ValueError, match="forbidden_tools"):
        sync.to_records(
            [{"id": "X", "category": "refusal", "question": "q", "expected_behavior": "refuse"}]
        )


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
    case = {"id": "X", "category": "refusal", "question": "q", "expected_behavior": "refuse"}
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
    assert check.check_counts(30, 31, 1).startswith("FALHA")  # órfã ou duplicada
    assert check.check_counts(30, 30, None).startswith("FALHA")


def test_dataset_is_linked_to_the_agent_experiment() -> None:
    # O MLflow gerenciado rejeita create_dataset sem experiment.
    assert sync.EXPERIMENT_NAME == "/Shared/atlas/agent"
    assert "experiment_id=[experiment.experiment_id]" in (
        ROOT / "eval" / "sync_golden_set.py"
    ).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM atlas.gold.fct_recharges",
        "SELECT 1 FROM atlas.semantic.mv_recharges JOIN atlas.silver.recharges USING (id)",
        "SELECT 1 FROM other.semantic.mv_recharges",
        "SELECT 1",
    ],
)
def test_reference_sql_must_read_only_atlas_semantic(sql: str) -> None:
    with pytest.raises(ValueError):
        sync.check_reads_only_semantic("X", sql)


def test_for_catalog_respects_identifier_boundary() -> None:
    sql = "SELECT 1 FROM my_atlas.semantic.x, atlas.semantic.mv_recharges"
    assert sync.for_catalog(sql, "atlas_dev") == (
        "SELECT 1 FROM my_atlas.semantic.x, atlas_dev.semantic.mv_recharges"
    )


def _row(case: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = sync.to_records([case])[0]
    return record


def test_mirror_detects_stale_rows_but_allows_additions() -> None:
    desired = sync.to_records(CASES)
    assert not sync.has_stale_rows([], desired)  # só faltam linhas: o merge soma
    assert not sync.has_stale_rows(desired[:5], desired)
    edited = {**CASES[0], "question": "pergunta com outra redação?"}
    assert sync.has_stale_rows([_row(edited), *desired[1:]], desired)  # editada: sobra a antiga
    extra = _row({**CASES[1], "id": "GS-999", "question": "outra pergunta?"})
    assert sync.has_stale_rows([*desired, extra], desired)  # removida do YAML
    changed = {**CASES[0], "tolerance_pct": 9.9}
    assert sync.has_stale_rows([_row(changed), *desired[1:]], desired)  # campo mudou


def test_mirror_ignores_extra_fields_and_json_strings() -> None:
    import json

    desired = sync.to_records(CASES)
    stored = [
        {
            "inputs": json.dumps(r["inputs"]),
            "expectations": json.dumps({**r["expectations"], "extra": 1}),
        }
        for r in desired
    ]
    assert not sync.has_stale_rows(stored, desired)
    sync.verify_mirror(stored, desired)


def test_verify_mirror_fails_on_divergence() -> None:
    desired = sync.to_records(CASES)
    with pytest.raises(RuntimeError):
        sync.verify_mirror(desired[:-1], desired)
    with pytest.raises(RuntimeError):
        sync.verify_mirror([*desired[:-1], desired[0]], desired)  # duplicada no lugar de uma


def test_is_not_found_only_for_missing_dataset() -> None:
    class Coded(Exception):
        error_code = "RESOURCE_DOES_NOT_EXIST"

    assert sync.is_not_found(Coded("x"))
    assert sync.is_not_found(RuntimeError("Table does not exist"))
    assert not sync.is_not_found(PermissionError("PERMISSION_DENIED: no access"))
    assert not sync.is_not_found(ConnectionError("timeout"))


def test_no_period_needs_the_month_sql() -> None:
    case = next(c for c in CASES if c["category"] == "no_period")
    broken = {k: v for k, v in case.items() if k != "reference_month_sql"}
    with pytest.raises(ValueError, match="reference_month_sql"):
        sync.to_records([broken])


def test_rows_of_an_empty_dataset_has_no_columns() -> None:
    class Frame:
        def __init__(self, columns: list[str], rows: list[dict[str, object]]) -> None:
            self.columns = columns
            self._rows = rows

        def __getitem__(self, _keys: list[str]) -> Frame:
            return self

        def to_dict(self, _orient: str) -> list[dict[str, object]]:
            return self._rows

    assert sync.rows_of(Frame([], [])) == []
    row: dict[str, object] = {"inputs": {"question": "q"}, "expectations": {"id": "A"}}
    assert sync.rows_of(Frame(["inputs", "expectations", "x"], [row])) == [row]
