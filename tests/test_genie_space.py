"""Consistency of the Genie Space resource in `databricks.yml` (SPEC-004 §6, P7.5)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
SPACE: dict[str, Any] = BUNDLE["resources"]["genie_spaces"]["atlas_recarga"]["serialized_space"]
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def test_space_reads_only_the_metric_view() -> None:
    tables = SPACE["data_sources"]["tables"]
    assert [t["identifier"] for t in tables] == ["${var.catalog}.semantic.mv_recharges"]
    for example in SPACE["instructions"]["example_question_sqls"]:
        sql = example["sql"][0].lower()
        assert "${var.catalog}.semantic.mv_recharges" in sql
        assert not re.search(r"\.(gold|silver|bronze|commission)\.", sql)
        assert "measure(" in sql


def test_space_has_ten_examples_with_the_ddd_one() -> None:
    examples = SPACE["instructions"]["example_question_sqls"]
    assert len(examples) == 10
    ddd = [e for e in examples if "DDD" in e["question"][0]]
    assert ddd and "ddd" in ddd[0]["sql"][0] and "gross_revenue" in ddd[0]["sql"][0]


def test_ids_are_32_hex_unique_and_sorted_per_array() -> None:
    groups = [
        SPACE["config"]["sample_questions"],
        SPACE["instructions"]["example_question_sqls"],
        SPACE["instructions"]["text_instructions"],
    ]
    seen: list[str] = []
    for group in groups:
        ids = [item["id"] for item in group]
        assert all(isinstance(i, str) and HEX32.match(i) for i in ids)
        assert ids == sorted(ids)
        seen += ids
    assert len(seen) == len(set(seen))


def test_text_instructions_are_one_item_under_the_size_limit() -> None:
    items = SPACE["instructions"]["text_instructions"]
    assert len(items) == 1
    assert sum(len(line) for line in items[0]["content"]) < 2000
