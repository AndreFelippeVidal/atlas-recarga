"""Lógica pura de `scripts/check_mcp_tools.py` (P11.3). Sem workspace."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_mcp_tools.py"
spec = importlib.util.spec_from_file_location("check_mcp_tools", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TOP: dict[str, Any] = {
    "rows": [["SP", "50"], ["RJ", "40"], ["MG", "30"], ["BA", "20"], ["PR", "10"]],
    "source": {"view": "x"},
    "sql_fingerprint": "a",
}
BY_UF: dict[str, Any] = {"rows": [["SP", "50"], ["RJ", "40"], ["AC", "1"]]}
COMPARE: dict[str, Any] = {
    "rows": [["SP", "40.00", "50.00", "10.00", "25.00"], ["AC", None, "1", None, None]],
    "source": {"view": "x"},
    "sql_fingerprint": "a",
}


def _eval(**over: Any) -> list[str]:
    args: dict[str, Any] = {
        "top": TOP,
        "by_uf": BY_UF,
        "compare": COMPARE,
        "municipality": "RESULT_TOO_LARGE: mais de 500 linhas",
        "invalid_error": "INVALID_ARGUMENT: level deve ser um de",
    }
    problems: list[str] = mod.evaluate(**{**args, **over})
    return problems


def test_all_good() -> None:
    assert _eval() == []


def test_unordered_top_is_reported() -> None:
    bad = {**TOP, "rows": list(reversed(TOP["rows"]))}
    assert _eval(top=bad)


def test_wrong_delta_is_reported() -> None:
    bad = {**COMPARE, "rows": [["SP", "40.00", "50.00", "11.00", "25.00"]]}
    assert any("delta_abs" in p for p in _eval(compare=bad))


def test_municipality_over_limit_without_error_is_reported() -> None:
    assert _eval(municipality={"rows": [[i] for i in range(501)]})


def test_municipality_within_limit_is_accepted() -> None:
    assert _eval(municipality={"rows": [[1]]}) == []


def test_missing_invalid_argument_is_reported() -> None:
    assert _eval(invalid_error=None)
