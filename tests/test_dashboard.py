"""Checks do dashboard "Atlas — Visão Comercial" (SPEC-004 §6, task P7.4). Sem workspace."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "semantic" / "dashboards" / "atlas_visao_comercial.lvdash.json"
MV = yaml.safe_load((ROOT / "semantic" / "mv_recharges.yaml").read_text(encoding="utf-8"))

DIMENSIONS = {d["name"] for d in MV["dimensions"]}
MEASURES = {m["name"] for m in MV["measures"]}
PAGES = {"brasil", "uf", "rede"}  # a página Comissão entra na P8.11 (mv_commission)
FILTER_FIELDS = {"recharge_month", "region", "uf"}


@pytest.fixture(scope="module")
def dash() -> dict[str, Any]:
    return json.loads(DASH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _widgets(dash: dict[str, Any]) -> list[dict[str, Any]]:
    return [item["widget"] for p in dash["pages"] for item in p["layout"]]


def test_pages(dash: dict[str, Any]) -> None:
    canvas = {p["name"] for p in dash["pages"] if p["pageType"] == "PAGE_TYPE_CANVAS"}
    assert canvas == PAGES


def test_single_dataset_over_metric_view(dash: dict[str, Any]) -> None:
    (ds,) = dash["datasets"]
    # Nome curto: o catálogo vem de dataset_catalog no bundle (muda por target).
    assert ds["asset_name"] == "mv_recharges"
    assert "queryLines" not in ds
    assert "columns" not in ds  # sem coluna derivada: nada de lógica fora da metric view


def test_global_filters_month_region_uf(dash: dict[str, Any]) -> None:
    (page,) = [p for p in dash["pages"] if p["pageType"] == "PAGE_TYPE_GLOBAL_FILTERS"]
    fields = {
        f["fieldName"]
        for item in page["layout"]
        for f in item["widget"]["spec"]["encodings"]["fields"]
    }
    assert fields == FILTER_FIELDS


def test_fields_exist_in_metric_view(dash: dict[str, Any]) -> None:
    for w in _widgets(dash):
        for q in w.get("queries", []):
            for f in q["query"]["fields"]:
                for m in re.findall(r"MEASURE\(`(\w+)`\)", f["expression"]):
                    assert m in MEASURES, (w["name"], m)
                if "MEASURE" not in f["expression"]:
                    assert f["name"] in DIMENSIONS, (w["name"], f["name"])


def test_encodings_match_query_fields(dash: dict[str, Any]) -> None:
    for w in _widgets(dash):
        if "spec" not in w or w["spec"]["widgetType"].startswith("filter"):
            continue
        names = {f["name"] for q in w["queries"] for f in q["query"]["fields"]}
        used = set(re.findall(r'"fieldName": "([^"]+)"', json.dumps(w["spec"]["encodings"])))
        assert used <= names, (w["name"], used - names)


def test_no_money_math_in_dashboard(dash: dict[str, Any]) -> None:
    # Princípio: métrica só na metric view; o dashboard não agrega receita por conta própria.
    for w in _widgets(dash):
        for q in w.get("queries", []):
            for f in q["query"]["fields"]:
                assert not re.match(r"(?i)(sum|avg|count)\(", f["expression"]), (w["name"], f)


def test_bundle_declares_dashboard() -> None:
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    d = bundle["resources"]["dashboards"]["atlas_visao_comercial"]
    assert d["file_path"] == "semantic/dashboards/atlas_visao_comercial.lvdash.json"
    assert d["dataset_catalog"] == "${var.catalog}"
    assert d["dataset_schema"] == "semantic"
    assert (ROOT / d["file_path"]).is_file()
