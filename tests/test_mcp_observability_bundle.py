"""Bundle, dashboard e setup das trace tables do MCP (P11.4). Sem workspace."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
DASH = json.loads(
    (ROOT / "semantic" / "dashboards" / "mcp_usage.lvdash.json").read_text(encoding="utf-8")
)
_spec = importlib.util.spec_from_file_location(
    "setup_mcp_trace_tables", ROOT / "scripts" / "setup_mcp_trace_tables.py"
)
assert _spec
assert _spec.loader
mod = importlib.util.module_from_spec(_spec)
sys.modules["setup_mcp_trace_tables"] = mod
_spec.loader.exec_module(mod)

SP = "1fdebf2b-83f2-4685-af7f-31f7b2e89a46"
USAGE_COLUMNS = {"day", "tool", "error_code", "calls", "duration_p95_ms"}


def test_app_writes_traces_only_to_the_mcp_experiment() -> None:
    assert BUNDLE["resources"]["experiments"]["atlas_mcp_traces"]["name"] == "/Shared/atlas/mcp"
    app = BUNDLE["resources"]["apps"]["atlas_mcp"]
    (exp,) = [r for r in app["resources"] if "experiment" in r]
    assert exp["experiment"]["experiment_id"] == "${resources.experiments.atlas_mcp_traces.id}"
    assert exp["experiment"]["permission"] == "CAN_EDIT"
    env = {e["name"]: e for e in app["config"]["env"]}
    assert env["MLFLOW_EXPERIMENT_ID"]["value_from"] == exp["name"]
    # Só warehouse (CAN_USE) e experiment: nenhum acesso a dados do UC.
    kinds = {key for r in app["resources"] for key in r if key != "name"}
    assert kinds == {"sql_warehouse", "experiment"}


def test_dashboard_reads_only_the_mcp_usage_view() -> None:
    dash = BUNDLE["resources"]["dashboards"]["mcp_usage"]
    assert dash["dataset_schema"] == "observability"
    assert dash["file_path"] == "semantic/dashboards/mcp_usage.lvdash.json"
    assert (ROOT / dash["file_path"]).exists()
    assert DASH["datasets"][0]["asset_name"] == mod.USAGE_VIEW
    (errors,) = [d for d in DASH["datasets"] if d["name"] == "ds_errors"]
    # Só erros: sem o filtro, as chamadas com sucesso (error_code vazio) viram uma barra sem rótulo.
    assert f"FROM {mod.USAGE_VIEW} WHERE error_code <> ''" in " ".join(errors["queryLines"])
    (page,) = DASH["pages"]
    assert page["displayName"] == "Uso do MCP"


def test_dashboard_shows_calls_errors_by_code_and_p95_per_tool() -> None:
    widgets = {w["widget"]["name"]: w["widget"] for w in DASH["pages"][0]["layout"]}
    fields = {
        name: {f["name"] for q in w.get("queries", []) for f in q["query"]["fields"]}
        for name, w in widgets.items()
    }
    assert {"calls", "tool", "day"} <= fields["u-calls-day"]
    assert {"error_code", "calls"} <= fields["u-errors-code"]
    assert {"duration_p95_ms", "tool", "day"} <= fields["u-p95-day"]
    for name in ("u-calls-day", "u-errors-code", "u-p95-day", "u-table"):
        assert fields[name] <= USAGE_COLUMNS


def test_usage_view_reads_only_span_attributes() -> None:
    sql = mod.usage_view_sql("atlas_dev")
    assert "FROM atlas_dev.observability.mcp_otel_spans" in sql
    assert "variant_get(attributes, '$.tool', 'string')" in sql
    assert "variant_get(attributes, '$.error_code', 'string')" in sql
    assert "attributes['" not in sql  # a coluna é VARIANT, não MAP
    assert "outputs" not in sql and "inputs" not in sql


def test_grants_are_minimal_and_per_object() -> None:
    stmts = mod.grant_statements(
        "atlas_dev", SP, [("mcp_otel_spans", "MANAGED"), ("mcp_trace_metadata", "VIEW")]
    )
    assert stmts[2].endswith(f"SELECT, MODIFY ON atlas_dev.observability.mcp_otel_spans TO `{SP}`")
    assert stmts[3] == f"GRANT SELECT ON atlas_dev.observability.mcp_trace_metadata TO `{SP}`"
    assert not any("ALL PRIVILEGES" in s for s in stmts)


@pytest.mark.parametrize(
    ("catalog", "principal", "tables"),
    [
        ("atlas; DROP", SP, []),
        ("atlas_dev", "x`; DROP", []),
        ("atlas_dev", SP, [("agent_otel_spans", "MANAGED")]),
        ("atlas_dev", SP, [("mcp_x; DROP TABLE y", "MANAGED")]),
    ],
)
def test_bad_input_is_rejected(catalog: str, principal: str, tables: list[tuple[str, str]]) -> None:
    with pytest.raises(ValueError):
        mod.grant_statements(catalog, principal, tables)


def test_usage_view_rejects_a_bad_catalog() -> None:
    with pytest.raises(ValueError):
        mod.usage_view_sql("atlas; DROP")


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
