"""Lógica pura de `scripts/check_mcp_query.py` (P11.2). Sem workspace."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_mcp_query.py"
spec = importlib.util.spec_from_file_location("check_mcp_query", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

LISTED: dict[str, Any] = {"views": {"mv_recharges": {}, "mv_commission": {}}}
BY_UF: dict[str, Any] = {
    "rows": [["SP", "10.50"], ["RJ", "4.50"]],
    "source": {"view": "x"},
    "sql_fingerprint": "a",
}
TOTAL: dict[str, Any] = {"rows": [["15.00"]]}


def _eval(**over: Any) -> list[str]:
    args: dict[str, Any] = {
        "listed": LISTED,
        "by_uf": BY_UF,
        "total": TOTAL,
        "invalid_error": "INVALID_ARGUMENT: measures fora da lista",
        "injection": {"rows": []},
    }
    problems: list[str] = mod.evaluate(**{**args, **over})
    return problems


def test_all_good() -> None:
    assert _eval() == []


def test_sum_mismatch_is_reported() -> None:
    assert any("difere" in p for p in _eval(total={"rows": [["15.01"]]}))


def test_missing_invalid_argument_is_reported() -> None:
    assert _eval(invalid_error=None)


def test_injection_returning_rows_is_reported() -> None:
    assert _eval(injection={"rows": [["x"]]})


def test_missing_view_is_reported() -> None:
    assert _eval(listed={"views": {"mv_recharges": {}}})


def test_bearer_token_parsing() -> None:
    assert mod.bearer_token({"Authorization": "Bearer abc"}) == "abc"
