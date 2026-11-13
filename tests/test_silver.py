"""Checks do silver: recargas, quarentena e dimensões (SPEC-002 §3, P6.2 a P6.4). Sem workspace."""

from __future__ import annotations

import ast
import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SILVER = ROOT / "pipeline" / "silver.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_silver_recharges", ROOT / "scripts" / "check_silver_recharges.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_silver_recharges"] = module
    spec.loader.exec_module(module)
    return module


def _recharges_decorators() -> dict[str, list[tuple[str, ...]]]:
    """decorator -> lista de argumentos literais, da função `recharges` de `silver.py`."""
    tree = ast.parse(SILVER.read_text(encoding="utf-8"))
    func = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "recharges"
    )
    found: dict[str, list[tuple[str, ...]]] = {}
    for deco in func.decorator_list:
        assert isinstance(deco, ast.Call)
        assert isinstance(deco.func, ast.Attribute)
        args = tuple(str(ast.literal_eval(a)) for a in deco.args)
        kwargs = tuple(str(ast.literal_eval(k.value)) for k in deco.keywords)
        found.setdefault(deco.func.attr, []).append(args + kwargs)
    return found


def test_silver_recharges_expectations_follow_the_spec() -> None:
    decorators = _recharges_decorators()
    assert decorators["expect_or_drop"] == [
        ("pos_not_null", "pos_id IS NOT NULL"),
        ("positive_amount", "amount_brl > 0"),
        ("valid_status", "status IN ('approved','reversed')"),
    ]
    assert decorators["expect"] == [("face_value", "amount_brl IN (10,15,20,25,30,40,50,100)")]
    assert "expect_or_fail" not in decorators


def test_silver_recharges_is_a_streaming_table_with_comment() -> None:
    table = _recharges_decorators()["table"]
    assert len(table) == 1
    assert table[0][0] == "silver.recharges"
    assert table[0][1]


def test_silver_derives_the_business_date_in_sao_paulo_and_dedups_by_id() -> None:
    text = SILVER.read_text(encoding="utf-8")
    assert 'BUSINESS_TZ = "America/Sao_Paulo"' in text
    assert 'dropDuplicates(["recharge_id"])' in text
    assert '"recharge_hour_local"' in text


def _pure_namespace() -> dict[str, Any]:
    """Executa só as constantes e `utc_offset_for_uf` de `silver.py` (sem importar pyspark)."""
    tree = ast.parse(SILVER.read_text(encoding="utf-8"))
    keep: list[ast.stmt] = []
    for node in tree.body:
        is_const = isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant | ast.Dict)
        is_fn = isinstance(node, ast.FunctionDef) and node.name == "utc_offset_for_uf"
        if is_const or is_fn:
            keep.append(node)
    namespace: dict[str, Any] = {}
    exec(compile(ast.Module(keep, []), str(SILVER), "exec"), namespace)  # noqa: S102
    return namespace


def _local_hour(ts_utc: datetime, uf: str | None) -> int:
    offset = _pure_namespace()["utc_offset_for_uf"](uf)
    sign = -1 if offset.startswith("-") else 1
    hours = int(offset[1:3])
    return (ts_utc + sign * timedelta(hours=hours)).hour


def test_local_hour_follows_the_uf_timezone() -> None:
    ts = datetime(2026, 3, 10, 2, 30, tzinfo=UTC)
    assert _local_hour(ts, "AC") == 21  # UTC-5, dia anterior
    assert _local_hour(ts, "AM") == 22
    assert _local_hour(ts, "MS") == 22
    assert _local_hour(ts, "SP") == 23  # UTC-3
    assert _local_hour(ts, "PA") == 23
    assert _local_hour(ts, None) == 23  # PDV órfão: padrão de Brasília


def test_every_uf_in_the_offset_map_is_a_real_brazilian_uf() -> None:
    ns = _pure_namespace()
    assert set(ns["UTC_OFFSET_BY_UF"]) == {"AC", "AM", "RO", "RR", "MT", "MS"}
    assert ns["utc_offset_for_uf"]("SP") == "-03:00"


def test_business_date_is_the_sao_paulo_day_not_the_utc_day() -> None:
    # 02:30 UTC de 11/03 ainda é 23:30 de 10/03 em São Paulo (UTC-3): o dia de negócio é 10.
    ts = datetime(2026, 3, 11, 2, 30, tzinfo=UTC)
    assert ts.astimezone(ZoneInfo(_pure_namespace()["BUSINESS_TZ"])).date() == date(2026, 3, 10)
    assert ts.date() == date(2026, 3, 11)


def test_expected_silver_count_subtracts_dups_nulls_negatives_and_orphans() -> None:
    script = _load_script()
    manifest = {
        "counts": {"recharges": 1_999_930},
        "scenarios": {
            "duplicates": {"rows": 4000},
            "null_pos": {"rows": 1000},
            "negative_amount": {"rows": 10},
            "unknown_pos": {"rows": 1000},
            "late_arrival": {"rows": 9915},
        },
    }
    assert script.expected_silver_count(manifest) == 1_999_930 - 4000 - 1000 - 10 - 1000


def test_expected_silver_count_without_scenarios_is_the_total() -> None:
    script = _load_script()
    assert script.expected_silver_count({"counts": {"recharges": 7}, "scenarios": {}}) == 7


def test_compare_flags_a_mismatch() -> None:
    script = _load_script()
    assert script.compare(10, 10).startswith("ok")
    assert script.compare(10, 9).startswith("FALHA")


def test_query_reads_only_silver_recharges() -> None:
    script = _load_script()
    assert "FROM atlas_dev.silver.recharges" in script.build_query("atlas_dev")


def test_bundle_registers_the_silver_file() -> None:
    text = (ROOT / "databricks.yml").read_text(encoding="utf-8")
    assert "pipeline/silver.py" in text


def test_quarantine_is_a_table_without_dropping_expectations() -> None:
    tree = ast.parse(SILVER.read_text(encoding="utf-8"))
    func = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "recharges_quarantine"
    )
    names = [d.func.attr for d in func.decorator_list if isinstance(d, ast.Call)]  # type: ignore[attr-defined]
    assert names == ["table"]  # reter, não descartar: sem expect_or_drop
    first = func.decorator_list[0]
    assert isinstance(first, ast.Call)
    assert ast.literal_eval(first.keywords[0].value) == "silver.recharges_quarantine"


def _join_types(func_name: str) -> list[str]:
    """Tipos (literais) dos `.join(..., "pos_id", <tipo>)` da função de `silver.py`."""
    tree = ast.parse(SILVER.read_text(encoding="utf-8"))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name)
    found: list[str] = []
    for node in ast.walk(func):
        is_join = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "join"
            and len(node.args) == 3
        )
        if is_join:
            assert isinstance(node, ast.Call)
            found.append(str(ast.literal_eval(node.args[2])))
    return found


def test_orphans_are_split_with_inner_join_and_anti_join() -> None:
    assert _join_types("recharges") == ["inner"]
    assert _join_types("recharges_quarantine") == ["left_anti"]
    assert 'F.col("pos_id").isNotNull()' in SILVER.read_text(encoding="utf-8")  # nulo não é órfão


def test_expected_quarantine_count_is_the_unknown_pos_rows() -> None:
    script = _load_script()
    manifest = {"counts": {"recharges": 9}, "scenarios": {"unknown_pos": {"rows": 1000}}}
    assert script.expected_quarantine_count(manifest) == 1000
    assert script.expected_quarantine_count({"counts": {"recharges": 9}}) == 0


def test_quarantine_query_and_closed_table_list() -> None:
    import pytest

    script = _load_script()
    assert "FROM atlas.silver.recharges_quarantine" in script.build_query(
        "atlas", "recharges_quarantine"
    )
    with pytest.raises(ValueError):
        script.build_query("atlas", "pos; DROP TABLE x")


def _decorators_of(func_name: str) -> dict[str, list[tuple[str, ...]]]:
    tree = ast.parse(SILVER.read_text(encoding="utf-8"))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name)
    found: dict[str, list[tuple[str, ...]]] = {}
    for deco in func.decorator_list:
        assert isinstance(deco, ast.Call)
        assert isinstance(deco.func, ast.Attribute)
        args = tuple(str(ast.literal_eval(a)) for a in deco.args)
        kwargs = tuple(str(ast.literal_eval(k.value)) for k in deco.keywords)
        found.setdefault(deco.func.attr, []).append(args + kwargs)
    return found


def test_silver_dimensions_are_materialized_views_that_fail_on_bad_integrity() -> None:
    for func, name in [
        ("municipalities", "silver.municipalities"),
        ("distributors", "silver.distributors"),
        ("pos", "silver.pos"),
    ]:
        decorators = _decorators_of(func)
        assert decorators["materialized_view"][0][0] == name
        assert decorators["materialized_view"][0][1]  # comment
        assert decorators["expect_or_fail"]
        assert "expect_or_drop" not in decorators  # dimensão corrompida falha, não descarta


def test_silver_pos_fails_on_unknown_municipality_and_missing_distributor() -> None:
    fails = {t[0]: t[1] for t in _decorators_of("pos")["expect_or_fail"]}
    assert fails["pos_municipality_known"] == "_municipality_in_reference"
    assert fails["pos_has_distributor"] == "_distributor_in_reference"
    assert fails["pos_pk_valid"] == "_pk_rows = 1"


def test_silver_pos_flags_are_false_when_the_reference_row_is_missing() -> None:
    """Um PDV de município inválido não casa no left join e vira `False` (critério 4)."""
    text = SILVER.read_text(encoding="utf-8")
    assert 'F.coalesce("_municipality_in_reference", F.lit(False))' in text
    assert 'F.coalesce("_distributor_in_reference", F.lit(False))' in text


def test_recharges_read_the_silver_dimensions_not_the_bronze() -> None:
    text = SILVER.read_text(encoding="utf-8")
    assert 'dp.read("silver.pos")' in text
    func_src = text[
        text.index("def known_pos") : text.index('@dp.table(\n    name="silver.recharges",')
    ]
    assert "bronze" not in func_src


def test_silver_pos_joins_are_left_so_an_invalid_pdv_fails_instead_of_vanishing() -> None:
    tree = ast.parse(SILVER.read_text(encoding="utf-8"))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "pos")
    types = [
        str(ast.literal_eval(n.args[2]))
        for n in ast.walk(func)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "join"
        and len(n.args) == 3
    ]
    assert types == ["left", "left"]
    assert "_pk_rows" in SILVER.read_text(encoding="utf-8")


def test_integrity_script_corrupts_only_the_first_pos_municipality(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    spec = importlib.util.spec_from_file_location(
        "check_silver_pos_integrity", ROOT / "scripts" / "check_silver_pos_integrity.py"
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    src = tmp_path / "pos.parquet"
    pq.write_table(
        pa.table({"pos_id": ["a", "b"], "municipality_ibge_code": ["3550308", "3304557"]}), src
    )
    dst = tmp_path / "out.parquet"
    module.corrupt_municipality(src, dst)
    assert pq.read_table(dst).column("municipality_ibge_code").to_pylist() == [
        "9999999",
        "3304557",
    ]
    assert pq.read_table(src).column("municipality_ibge_code").to_pylist()[0] == "3550308"
    assert set(module.LANDING) == {"dev"}  # nunca toca o demo
