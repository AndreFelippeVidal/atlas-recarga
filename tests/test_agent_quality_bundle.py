"""Bundle e dashboard do monitoramento do agente (P10.8). Sem workspace."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
DASH = json.loads(
    (ROOT / "semantic" / "dashboards" / "agent_quality.lvdash.json").read_text(encoding="utf-8")
)

_spec = importlib.util.spec_from_file_location("monitoring", ROOT / "eval" / "monitoring.py")
assert _spec
assert _spec.loader
mon = importlib.util.module_from_spec(_spec)
sys.modules["monitoring"] = mon
_spec.loader.exec_module(mon)


def test_job_runs_daily_at_7_after_atlas_daily() -> None:
    job = BUNDLE["resources"]["jobs"]["atlas_agent_monitoring"]
    assert job["schedule"]["quartz_cron_expression"] == "0 0 7 * * ?"
    assert job["schedule"]["timezone_id"] == "America/Sao_Paulo"
    (task,) = job["tasks"]
    assert task["spark_python_task"]["python_file"] == "eval/run_agent_monitoring.py"
    params = task["spark_python_task"]["parameters"]
    assert params[0] == "${var.catalog}"
    # Sem __file__ no serverless: o caminho de eval/ e o id do experiment vêm do bundle.
    assert params[params.index("--eval-dir") + 1] == "${workspace.file_path}/eval"
    assert (
        params[params.index("--experiment-id") + 1]
        == "${resources.experiments.atlas_agent_traces.id}"
    )


def test_alert_watches_the_alert_view_below_90_percent() -> None:
    alert = BUNDLE["resources"]["alerts"]["agent_quality_below_90"]
    assert "observability.agent_quality_alert" in alert["query_text"]
    assert alert["evaluation"]["comparison_operator"] == "LESS_THAN"
    assert alert["evaluation"]["threshold"]["value"]["double_value"] == mon.ALERT_THRESHOLD
    (subscription,) = alert["evaluation"]["notification"]["subscriptions"]
    # Sem e-mail fixo no repositório: é quem faz o deploy.
    assert subscription["user_email"] == "${workspace.current_user.userName}"


def test_dashboard_is_registered_on_observability_not_semantic() -> None:
    dash = BUNDLE["resources"]["dashboards"]["agent_quality"]
    assert dash["dataset_schema"] == "observability"
    assert dash["file_path"] == "semantic/dashboards/agent_quality.lvdash.json"


def test_dashboard_reads_only_the_two_views_without_derived_logic() -> None:
    assert {d["name"]: d["asset_name"] for d in DASH["datasets"]} == {
        "ds_daily": "agent_quality_daily",
        "ds_traffic": "agent_traffic_daily",
    }
    for dataset in DASH["datasets"]:
        assert "queryLines" not in dataset


def test_dashboard_widgets_only_use_columns_the_views_define() -> None:
    ddl = "\n".join(mon.ddl("atlas"))
    columns: dict[str, set[str]] = {}
    for view in ("agent_quality_daily", "agent_traffic_daily"):
        block = re.search(rf"{view} \((.*?)\)\nCOMMENT", ddl, re.S)
        assert block
        columns[view] = set(re.findall(r"^\s*(\w+) COMMENT", block.group(1), re.M))
    by_dataset = {d["name"]: columns[d["asset_name"]] for d in DASH["datasets"]}
    widgets: list[dict[str, Any]] = [i["widget"] for p in DASH["pages"] for i in p["layout"]]
    used = 0
    for widget in widgets:
        for q in widget.get("queries", []):
            query = q["query"]
            for field in query["fields"]:
                for name in re.findall(r"`(\w+)`", field["expression"]):
                    assert name in by_dataset[query["datasetName"]], (widget["name"], name)
                    used += 1
    assert used > 10


def test_dashboard_has_the_spec_panels() -> None:
    names = {i["widget"]["name"] for p in DASH["pages"] for i in p["layout"]}
    # % de pass por dia, média de 7 dias, latência p95 e volume (SPEC-008 §6).
    assert {"q-pass-day", "q-pass-7d", "q-p95-line", "q-volume"} <= names
