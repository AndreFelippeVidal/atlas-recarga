"""Tests for .claude/hooks/guard.py (SPEC-010 §4, §8).

Every rule in RULES (plus the dynamic push-from-main rule) must have at least one
positive case (it fires) and one negative case (a near miss that must not fire).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD_PATH = ROOT / ".claude" / "hooks" / "guard.py"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)}


def tool(name: str, path: str) -> dict[str, Any]:
    return {"tool_name": name, "tool_input": {"file_path": path}, "cwd": str(ROOT)}


# (rule_id, payload, branch) -> must fire with that rule
POSITIVE: list[tuple[str, dict[str, Any], str | None]] = [
    ("merge-pr", bash("gh pr merge 9 --squash"), "task/x"),
    ("merge-pr", bash('sh -c "gh pr merge 9"'), "task/x"),
    ("merge-api", bash("gh api -X PUT repos/o/r/pulls/9/merge"), "task/x"),
    ("push-main", bash("git push origin main"), "task/x"),
    ("push-main", bash("git push origin HEAD:main"), "task/x"),
    ("push-force", bash("git push --force origin task/x"), "task/x"),
    ("push-force", bash("git push -f origin task/x"), "task/x"),
    ("push-force", bash("git push origin +task/x"), "task/x"),
    ("push-force", bash("git push origin --delete task/x"), "task/x"),
    ("repo-protection", bash("gh api -X PUT repos/o/r/branches/main/protection"), "task/x"),
    ("repo-settings", bash("gh repo edit --visibility private"), "task/x"),
    ("repo-settings", bash("gh secret set TOKEN"), "task/x"),
    ("repo-patch", bash("gh api -X PATCH repos/o/r -f allow_merge_commit=true"), "task/x"),
    ("deploy-demo", bash("databricks bundle deploy -t demo"), "task/x"),
    ("deploy-demo", bash("databricks bundle deploy --target=demo"), "task/x"),
    ("commission-review", bash("databricks jobs run-now --job-name atlas_commission_review"), None),
    ("secret-file-cmd", bash("cat .env"), "task/x"),
    ("secret-file-cmd", bash("cat apps/agent/.env.local"), "task/x"),
    ("secret-file-cmd", bash("cat ~/.databrickscfg"), "task/x"),
    ("secret-file-cmd", bash("openssl rsa -in server.key"), "task/x"),
    ("secret-token-cmd", bash("gh auth token"), "task/x"),
    ("secret-token-cmd", bash("databricks auth token --host x"), "task/x"),
    ("dump-env", bash("printenv"), "task/x"),
    ("dump-env", bash("ls && env"), "task/x"),
    ("no-verify", bash("git commit -m x --no-verify"), "task/x"),
    ("secret-file-path", tool("Read", ".env"), None),
    ("secret-file-path", tool("Read", str(ROOT / "apps" / ".env.production")), None),
    ("secret-file-path", tool("Edit", "certs/client.pem"), None),
    ("deploy", bash("databricks bundle deploy -t dev"), "task/x"),
    ("workspace-write", bash("uv run atlas-cli upload --to /Volumes/atlas/raw"), "task/x"),
    ("workspace-write", bash("databricks jobs run-now 123"), "task/x"),
    ("workspace-write", bash("databricks fs cp a dbfs:/b"), "task/x"),
    ("edit-spec", tool("Edit", "docs/specs/003-commission-closing/spec.md"), None),
    ("edit-spec", tool("Write", "docs/specs/mission.md"), None),
    ("edit-spec", tool("Edit", "docs/adr/0010-commission-human-in-the-loop.md"), None),
    ("edit-sensitive", tool("Edit", "commission/rules.py"), None),
    ("edit-sensitive", tool("Write", "semantic/mv_recharges.yaml"), None),
    ("edit-sensitive", tool("Edit", ".claude/settings.json"), None),
    ("edit-sensitive", tool("Edit", ".github/workflows/ci.yml"), None),
    ("push-from-main", bash("git push"), "main"),
    ("push-from-main", bash("git push -u origin HEAD"), "main"),
]

# near misses that must not trigger the named rule (and, unless noted, nothing at all)
NEGATIVE: list[tuple[str, dict[str, Any], str | None]] = [
    ("merge-pr", bash("gh pr view 9"), "task/x"),
    ("merge-api", bash("gh api repos/o/r/pulls/9"), "task/x"),
    ("push-main", bash("git push -u origin task/P1.3-maintenance"), "task/x"),
    ("push-force", bash("git push -u origin task/x"), "task/x"),
    ("repo-protection", bash("gh api repos/o/r/codeowners/errors"), "task/x"),
    ("repo-settings", bash("gh repo view --json url"), "task/x"),
    ("repo-patch", bash("gh api repos/o/r/pulls/9/comments"), "task/x"),
    ("deploy-demo", bash("databricks bundle validate -t demo"), "task/x"),
    ("commission-review", bash("uv run pytest tests/test_commission_review.py"), "task/x"),
    ("secret-file-cmd", bash("cp .env.example .env.example.bak"), "task/x"),
    ("secret-file-cmd", bash("cat .envrc.md README.md"), "task/x"),
    ("secret-token-cmd", bash("gh auth status"), "task/x"),
    ("dump-env", bash("env FOO=1 uv run pytest"), "task/x"),
    ("no-verify", bash("git commit -m 'verify the pipeline'"), "task/x"),
    ("secret-file-path", tool("Read", ".env.example"), None),
    ("deploy", bash("databricks bundle validate -t dev"), "task/x"),
    ("workspace-write", bash("uv run atlas-cli generate --seed 42"), "task/x"),
    ("edit-spec", tool("Edit", "docs/specs/roadmap.md"), None),
    ("edit-spec", tool("Edit", "docs/specs/003-commission-closing/tasks.md"), None),
    ("edit-sensitive", tool("Edit", "commission/calculate.py"), None),
    ("edit-sensitive", tool("Edit", ".github/pull_request_template.md"), None),
    ("push-from-main", bash("git push -u origin task/P1.3-x"), "main"),
    ("push-from-main", bash("git push"), "task/P1.3-x"),
]


@pytest.mark.parametrize(("rule_id", "payload", "branch"), POSITIVE)
def test_rule_fires(rule_id: str, payload: dict[str, Any], branch: str | None) -> None:
    result = guard.decide(payload, branch=branch)
    assert result is not None, f"expected {rule_id} to fire"
    assert result.rule_id == rule_id


@pytest.mark.parametrize(("rule_id", "payload", "branch"), NEGATIVE)
def test_rule_does_not_fire(rule_id: str, payload: dict[str, Any], branch: str | None) -> None:
    result = guard.decide(payload, branch=branch)
    assert result is None or result.rule_id != rule_id


def test_negatives_are_fully_clean() -> None:
    """Near misses must not be caught by *any* rule (low false-positive rate)."""
    noisy = [
        (rid, guard.decide(p, branch=b).rule_id)
        for rid, p, b in NEGATIVE
        if guard.decide(p, branch=b) is not None
    ]
    assert noisy == []


def test_every_rule_has_positive_and_negative_cases() -> None:
    ids = {r.id for r in guard.RULES} | {guard.PUSH_FROM_MAIN}
    assert ids - {r for r, _, _ in POSITIVE} == set(), "rules without a positive case"
    assert ids - {r for r, _, _ in NEGATIVE} == set(), "rules without a negative case"


def test_deny_wins_over_ask() -> None:
    result = guard.decide(bash("databricks bundle deploy -t demo"), branch="task/x")
    assert result is not None and result.decision == guard.DENY


def test_unrelated_tools_are_ignored() -> None:
    assert guard.decide({"tool_name": "Grep", "tool_input": {"pattern": ".env"}}) is None


def run_hook(stdin: str) -> dict[str, Any]:
    # Point the hook at a throwaway project dir so tests never write the real hooks.log.
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run(  # noqa: S603
            [sys.executable, str(GUARD_PATH)],
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
            env={**os.environ, "CLAUDE_PROJECT_DIR": tmp},
        )
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_cli_emits_deny_json() -> None:
    output = run_hook(json.dumps(bash("gh pr merge 1")))
    decision = output["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    assert "ADR-0014" in decision["permissionDecisionReason"]


def test_cli_emits_nothing_when_no_objection() -> None:
    assert run_hook(json.dumps(bash("uv run pytest"))) == {}


@pytest.mark.parametrize("stdin", ["not json", "[]", json.dumps({"tool_name": "Bash"})])
def test_cli_fails_closed(stdin: str) -> None:
    output = run_hook(stdin)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_settings_register_the_guard_and_core_denies() -> None:
    """SPEC-010 §2 layer 1: settings.json is valid and wires layer 2 (the hook)."""
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]["PreToolUse"]
    commands = [h["command"] for entry in hooks for h in entry["hooks"]]
    assert any(".claude/hooks/guard.py" in c for c in commands)
    matchers = {m for entry in hooks for m in entry["matcher"].split("|")}
    assert {"Bash", "Edit", "Write", "Read"} <= matchers
    assert GUARD_PATH.stat().st_mode & 0o111, "guard.py must be executable"
    deny = set(settings["permissions"]["deny"])
    assert {"Bash(gh pr merge*)", "Bash(git push --force*)", "Read(./.env)"} <= deny
    assert not set(settings["permissions"]["allow"]) & deny
