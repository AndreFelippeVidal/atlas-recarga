"""Lógica pura de `scripts/check_mcp_parity.py` (P11.4). Sem workspace."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "check_mcp_parity", ROOT / "scripts" / "check_mcp_parity.py"
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CASES = yaml.safe_load((ROOT / "eval" / "golden_set.yaml").read_text(encoding="utf-8"))


def test_every_metric_case_translates_to_a_closed_list_query() -> None:
    from atlas_mcp.catalog import load_catalog

    views = load_catalog()["views"]
    metric = [c for c in CASES if c["category"] == "metric"]
    assert len(metric) == 23
    for case in metric:
        call = mod.translate(case["reference_sql"])
        assert call is not None, case["id"]
        spec_view = views[call["view"]]
        assert call["measures"][0] in [m["name"] for m in spec_view["measures"]], case["id"]
        dims = [d["name"] for d in spec_view["dimensions"]]
        assert set(call["filters"]) <= set(dims), case["id"]


def test_translate_reads_filters_scale_and_month() -> None:
    sql = (
        "SELECT MEASURE(gross_revenue) AS value FROM atlas.semantic.mv_recharges "
        "WHERE uf = 'PA' AND recharge_month = DATE'2026-10-01'"
    )
    assert mod.translate(sql) == {
        "view": "mv_recharges",
        "measures": ["gross_revenue"],
        "dimensions": [],
        "filters": {"uf": "PA"},
        "month_from": "2026-10",
        "month_to": "2026-10",
        "scale": Decimal(1),
    }
    scaled = mod.translate(
        "SELECT MEASURE(effective_rate) * 100 AS value FROM atlas.semantic.mv_commission "
        "WHERE reference_month = DATE'2026-10-01'"
    )
    assert scaled is not None and scaled["scale"] == Decimal(100) and scaled["filters"] == {}


def test_translate_rejects_unexpected_shapes() -> None:
    assert mod.translate("SELECT 1") is None
    assert (
        mod.translate(
            "SELECT MEASURE(a) AS value FROM atlas.semantic.mv_recharges "
            "WHERE recharge_month = DATE'2026-10-01' OR uf > 'A'"
        )
        is None
    )


def test_compare_reports_ok_and_failures() -> None:
    assert mod.compare("GS-1", Decimal("4122460.00"), "4122460.00").startswith("ok")
    assert mod.compare("GS-6", Decimal("1.0000000001"), "1").startswith("ok")
    assert mod.compare("GS-1", Decimal("4122460.01"), "4122460.00").startswith("FALHA")
    assert mod.compare("GS-1", None, "1").startswith("FALHA")
