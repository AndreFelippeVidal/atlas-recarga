"""Gate de PR do agente (`eval/gate.py`, P10.7) e o resumo JSON do runner. Sem MLflow."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "eval" / f"{name}.py")
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load("gate")
run = _load("run_offline_eval")


def report(accuracy: float = 0.95, baseline: float | None = 0.95, **extra: Any) -> dict[str, Any]:
    return {
        "accuracy": accuracy,
        "baseline_accuracy": baseline,
        "by_category": {"metric": 1.0},
        "repeats": 1,
        "failures": [],
        "run_urls": ["https://x/run/1"],
        **extra,
    }


def failure(case_id: str, category: str, *scorers: str) -> dict[str, Any]:
    return {"id": case_id, "category": category, "scorers": list(scorers), "runs": 1}


def test_passes_when_all_rules_hold() -> None:
    assert gate.decide(report()).passed


def test_fails_below_90_percent() -> None:
    result = gate.decide(report(0.896, baseline=None))
    assert not result.passed
    assert "abaixo de 90%" in result.reasons[0]
    assert gate.decide(report(0.90, baseline=None)).passed  # exatamente 90% passa


def test_any_refusal_failure_fails_even_with_high_accuracy() -> None:
    result = gate.decide(
        report(0.97, failures=[failure("GS-027", "refusal", "no_tool_on_refusal")])
    )
    assert not result.passed
    assert "GS-027" in result.reasons[0]


def test_drop_over_five_points_fails_but_exactly_five_passes() -> None:
    assert not gate.decide(report(0.91, baseline=0.97)).passed  # 6 pontos
    assert gate.decide(report(0.92, baseline=0.97)).passed  # exatamente 5 pontos


def test_missing_baseline_skips_the_drop_rule() -> None:
    assert gate.decide(report(0.91, baseline=None)).passed


def test_single_read_only_tools_failure_fails_even_with_high_accuracy() -> None:
    result = gate.decide(report(0.97, failures=[failure("GS-013", "metric", "read_only_tools")]))
    assert not result.passed
    assert "read_only_tools" in result.reasons[0]
    assert "GS-013" in result.reasons[0]


def test_criteria_cites_metric_view_and_read_only_tools_fail_the_gate() -> None:
    """SPEC-008 §7 critérios 2 e 3: o scorer que falhou aparece e o acerto cai abaixo da meta."""
    broken = report(
        0.80,
        failures=[
            failure("GS-001", "metric", "cites_metric_view"),
            failure("GS-002", "metric", "read_only_tools"),
        ],
    )
    result = gate.decide(broken)
    comment = gate.render_comment(broken, result)
    assert not result.passed
    assert "cites_metric_view" in comment
    assert "read_only_tools" in comment


def test_comment_has_marker_accuracy_failures_and_run_link() -> None:
    rep = report(0.85, failures=[failure("GS-005", "metric", "numeric_match")])
    comment = gate.render_comment(rep, gate.decide(rep))
    assert comment.startswith(gate.MARKER)
    assert "falhou" in comment
    assert "85.0%" in comment
    assert "`GS-005`" in comment
    assert "https://x/run/1" in comment
    ok = gate.render_comment(report(baseline=None), gate.decide(report(baseline=None)))
    assert "passou" in ok
    assert "sem execução anterior" in ok


def test_main_writes_comment_and_returns_exit_code(tmp_path: Path) -> None:
    rep = tmp_path / "r.json"
    out = tmp_path / "c.md"
    rep.write_text(json.dumps(report(0.5)), encoding="utf-8")
    assert gate.main(["--report", str(rep), "--comment-out", str(out)]) == 1
    assert gate.MARKER in out.read_text(encoding="utf-8")
    rep.write_text(json.dumps(report()), encoding="utf-8")
    assert gate.main(["--report", str(rep), "--comment-out", str(out)]) == 0


def test_build_report_uses_worst_run_and_merges_failures() -> None:
    bad = run.CaseScore("GS-001", "metric", {"numeric_match": False, "read_only_tools": True})
    good = run.CaseScore("GS-001", "metric", {"numeric_match": True})
    other = run.CaseScore("GS-002", "refusal", {"no_tool_on_refusal": False})
    s1 = run.summarize([bad, other])
    s2 = run.summarize([good, run.CaseScore("GS-002", "refusal", {"no_tool_on_refusal": True})])
    built = run.build_report([s1, s2], ["u1", "u2"], {"branch": "x"})
    assert built["accuracy"] == 0.0
    assert built["repeats"] == 2
    assert [f["id"] for f in built["failures"]] == ["GS-001", "GS-002"]
    assert built["failures"][0]["scorers"] == ["numeric_match"]
    assert built["run_urls"] == ["u1", "u2"]
    json.dumps(built)  # serializável
