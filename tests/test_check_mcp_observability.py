"""Lógica pura de `scripts/check_mcp_observability.py` (P11.4). Sem workspace."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_mcp_observability.py"
spec = importlib.util.spec_from_file_location("check_mcp_observability", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

RID = "123e4567-e89b-42d3-a456-426614174000"
OK_ATTRS = {
    "request_id": RID,
    "user": "ana@x.com",
    "tool": "query_metric",
    "app_version": "0.1.0",
    "error_code": "",
    "duration_ms": 12,
    "sql_fingerprint": "f",
    "rows": 3,
}


def _spans() -> list[dict[str, Any]]:
    return [{"attributes": {**OK_ATTRS, "tool": t}, "outputs": None} for t in mod.TOOLS]


def test_spans_ok_and_each_problem() -> None:
    assert mod.check_spans(_spans()) == []
    assert any("sem trace" in p for p in mod.check_spans(_spans()[:3]))
    leaking = _spans()
    leaking[2]["outputs"] = {"rows": [["SP", "1"]]}
    assert any("outputs" in p for p in mod.check_spans(leaking))
    missing = _spans()
    del missing[0]["attributes"]["duration_ms"]
    assert any("duration_ms" in p for p in mod.check_spans(missing))
    no_fp = _spans()
    del no_fp[2]["attributes"]["sql_fingerprint"]
    assert any("sql_fingerprint" in p for p in mod.check_spans(no_fp))


def test_rate_limit_31st_call() -> None:
    msg = f"RATE_LIMITED: limite; retry_after_s=40 request_id={RID}"
    problems, rid = mod.check_rate_limit([None] * 30 + [msg])
    assert problems == [] and rid == RID
    problems, _ = mod.check_rate_limit([None] * 31)
    assert any("31ª" in p for p in problems)
    problems, _ = mod.check_rate_limit([None] * 29 + [msg, msg])
    assert any("só 29" in p for p in problems)
    problems, rid = mod.check_rate_limit([None] * 30 + ["RATE_LIMITED: sem nada"])
    assert rid is None and problems


def test_history_obo_and_plan_b() -> None:
    rows = [["ana@x.com", f"/* atlas-mcp request_id={RID[:-1]}1 */ SELECT 1"]]
    assert mod.check_history(rows, RID, "ana@x.com", "obo", ["ana@x.com"]) == []
    other = [["sp-uuid", rows[0][1]]]
    assert mod.check_history(other, RID, "ana@x.com", "obo", []) != []
    assert mod.check_history(other, RID, "ana@x.com", "service-principal", ["ana@x.com"]) == []
    assert mod.check_history(rows, RID, "ana@x.com", "service-principal", ["ana@x.com"]) != []
    leaked = [["ana@x.com", f"/* atlas-mcp request_id={RID} */ SELECT 1"]]
    assert any("RATE_LIMITED" in p for p in mod.check_history(leaked, RID, "ana@x.com", "obo", []))
    assert mod.check_history([], None, "ana@x.com", "obo", []) != []
