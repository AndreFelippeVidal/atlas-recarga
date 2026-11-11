"""Tests for .claude/hooks/guard.py and .claude/settings.json (SPEC-010 §2-§4, §8).

Every rule in RULES (plus the dynamic push-from-main rule) must have at least one
positive case (fires with the expected decision) and one negative case (a near miss
that must not fire). Bypasses found in review are kept as regression cases.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD_PATH = ROOT / ".claude" / "hooks" / "guard.py"
SETTINGS_PATH = ROOT / ".claude" / "settings.json"


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()
D, A = "deny", "ask"
T = "task/x"  # a non-main current branch


def bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(ROOT)}


def tool(name: str, path: str, key: str = "file_path") -> dict[str, Any]:
    return {"tool_name": name, "tool_input": {key: path}, "cwd": str(ROOT)}


# (rule_id, expected decision, payload, current branch)
POSITIVE: list[tuple[str, str, dict[str, Any], str | None]] = [
    # merge
    ("merge-pr", D, bash("gh pr merge 9 --squash"), T),
    ("merge-pr", D, bash('sh -c "gh pr merge 9"'), T),
    ("merge-pr", D, bash("gh -R o/r pr merge 9"), T),
    ("merge-pr", D, bash("gh --repo=o/r pr merge 9"), T),
    ("merge-pr", D, bash('gh pr "merge" 9'), T),
    ("merge-api", D, bash("gh api -X PUT repos/o/r/pulls/9/merge"), T),
    ("merge-api", D, bash("gh api repos/o/r/pulls/9/merge --method=PUT"), T),
    ("merge-api", D, bash("gh api repos/o/r/merges -f base=main -f head=task/x"), T),
    ("merge-api", D, bash("gh api graphql -f query='mutation{mergePullRequest(input:{})}'"), T),
    ("gh-alias", D, bash("gh alias set m 'pr merge'"), T),
    # main and remote history
    ("push-main", D, bash("git push origin main"), T),
    ("push-main", D, bash("git push origin HEAD:main"), T),
    ("push-main", D, bash("git push origin task/x:main"), T),
    ("push-main", D, bash("git -C . push origin main"), T),
    ("push-main", D, bash("git --no-pager -c x=y push origin main"), T),
    ("push-force", D, bash("git push --force origin task/x"), T),
    ("push-force", D, bash("git push -f origin task/x"), T),
    ("push-force", D, bash("git push -uf origin task/x"), T),
    ("push-force", D, bash("git push origin +task/x"), T),
    ("push-force", D, bash("git push origin --delete task/x"), T),
    ("push-force", D, bash("git push -d origin task/x"), T),
    ("push-force", D, bash("git push origin :task/x"), T),
    ("push-force", D, bash("git push --mirror"), T),
    ("push-from-main", D, bash("git push"), "main"),
    ("push-from-main", D, bash("git push -u origin HEAD"), "main"),
    ("push-from-main", D, bash("git commit -m 'task/P1.3 done' && git push"), "main"),
    # repository configuration
    ("repo-protection", D, bash("gh api -X PUT repos/o/r/branches/main/protection"), T),
    ("repo-settings", D, bash("gh repo edit --visibility private"), T),
    ("repo-settings", D, bash("gh secret set TOKEN"), T),
    ("repo-settings", D, bash("gh -R o/r secret list"), T),
    ("repo-patch", D, bash("gh api -X PATCH repos/o/r -f allow_merge_commit=true"), T),
    ("repo-patch", D, bash("gh api repos/o/r -X PATCH -f allow_merge_commit=true"), T),
    ("repo-patch", D, bash("gh api --method=PATCH repos/o/r -f x=1"), T),
    ("repo-graphql", D, bash("gh api graphql -f query='mutation{updateRepository(input:{})}'"), T),
    # Databricks
    ("deploy-demo", D, bash("databricks bundle deploy -t demo"), T),
    ("deploy-demo", D, bash("databricks bundle deploy --target=demo"), T),
    ("deploy-demo", D, bash("databricks bundle deploy -tdemo"), T),
    ("commission-review", D, bash("databricks jobs run-now --job-name atlas_commission_review"), T),
    # secrets
    ("secret-file-cmd", D, bash("cat .env"), T),
    ("secret-file-cmd", D, bash("cat apps/agent/.env.local"), T),
    ("secret-file-cmd", D, bash("grep TOKEN .env*"), T),
    ("secret-file-cmd", D, bash("cat .en''v"), T),
    ("secret-file-cmd", D, bash("cat ~/.databrickscfg"), T),
    ("secret-file-cmd", D, bash("openssl rsa -in server.key"), T),
    ("secret-token-cmd", D, bash("gh auth token"), T),
    ("secret-token-cmd", D, bash("databricks auth token --host x"), T),
    ("dump-env", D, bash("printenv"), T),
    ("dump-env", D, bash("printenv GH_TOKEN"), T),
    ("dump-env", D, bash("echo $(printenv)"), T),
    ("dump-env", D, bash("ls && env"), T),
    ("dump-env", D, bash("ls\nenv"), T),
    ("dump-env", D, bash('sh -c "env"'), T),
    ("dump-env", D, bash("export"), T),
    ("dump-env", D, bash("declare -x"), T),
    ("dump-env", D, bash("env -0"), T),
    # skipping local hooks
    ("no-verify", D, bash("git commit -m x --no-verify"), T),
    ("no-verify", D, bash("git commit -n -m x"), T),
    ("no-verify", D, bash("git commit -anm x"), T),
    ("no-verify", D, bash("git -c core.hooksPath=/dev/null commit -m x"), T),
    ("no-verify", D, bash("SKIP=gitleaks git commit -m x"), T),
    # file tools
    ("secret-file-path", D, tool("Read", ".env"), None),
    ("secret-file-path", D, tool("Read", str(ROOT / "apps" / ".env.production")), None),
    ("secret-file-path", D, tool("Edit", "certs/client.pem"), None),
    ("secret-file-path", D, tool("Grep", ".env.staging", key="path"), None),
    ("secret-file-path", D, tool("Glob", "certs/x.key", key="path"), None),
    # ask
    ("deploy", A, bash("databricks bundle deploy -t dev"), T),
    ("workspace-write", A, bash("uv run atlas-cli upload --to /Volumes/atlas/raw"), T),
    ("workspace-write", A, bash("databricks jobs run-now 123"), T),
    ("workspace-write", A, bash("databricks fs cp a dbfs:/b"), T),
    ("edit-spec", A, tool("Edit", "docs/specs/003-commission-closing/spec.md"), None),
    ("edit-spec", A, tool("Edit", "docs/specs/003-x/sub/spec.md"), None),
    ("edit-spec", A, tool("Write", "docs/specs/mission.md"), None),
    ("edit-spec", A, tool("Edit", "docs/adr/0010-commission-human-in-the-loop.md"), None),
    ("edit-sensitive", A, tool("Edit", "commission/rules.py"), None),
    ("edit-sensitive", A, tool("Write", "semantic/mv_recharges.yaml"), None),
    ("edit-sensitive", A, tool("Edit", ".claude/settings.json"), None),
    ("edit-sensitive", A, tool("Edit", ".github/workflows/ci.yml"), None),
]

# near misses that must not trigger the named rule (nor any other rule)
NEGATIVE: list[tuple[str, dict[str, Any], str | None]] = [
    ("merge-pr", bash("gh pr view 9"), T),
    ("merge-api", bash("gh api repos/o/r/pulls/9/merge"), T),  # GET: "is it merged?"
    ("gh-alias", bash("gh alias list"), T),
    ("push-main", bash("git push -u origin task/P1.3-maintenance"), T),
    ("push-main", bash("git push origin task/x\necho main"), T),
    ("push-force", bash("git push -u origin task/x"), T),
    ("push-from-main", bash("git push -u origin task/P1.3-x"), "main"),
    ("push-from-main", bash("git push"), "task/P1.3-x"),
    ("repo-protection", bash("gh api repos/o/r/codeowners/errors"), T),
    ("repo-settings", bash("gh repo view --json url"), T),
    ("repo-patch", bash("gh api repos/o/r/pulls/9/comments"), T),
    ("repo-graphql", bash("gh api graphql -f query='{repository(owner:o,name:r){id}}'"), T),
    ("deploy-demo", bash("databricks bundle validate -t demo"), T),
    ("commission-review", bash("uv run pytest tests/test_commission_review.py"), T),
    ("secret-file-cmd", bash("cp .env.example .env.example.bak"), T),
    ("secret-file-cmd", bash("cat .envrc.md README.md"), T),
    ("secret-token-cmd", bash("gh auth status"), T),
    ("dump-env", bash("env FOO=1 uv run pytest"), T),
    ("dump-env", bash("export FOO=1 && set -e"), T),
    ("dump-env", bash("git commit -m 'add env var docs'"), T),
    ("no-verify", bash("git commit -m 'verify the pipeline'"), T),
    ("no-verify", bash("git commit -am 'fix'"), T),
    ("secret-file-path", tool("Read", ".env.example"), None),
    ("secret-file-path", tool("Grep", "src", key="path"), None),
    ("deploy", bash("databricks bundle validate -t dev"), T),
    ("workspace-write", bash("uv run atlas-cli generate --seed 42"), T),
    ("edit-spec", tool("Edit", "docs/specs/roadmap.md"), None),
    ("edit-spec", tool("Edit", "docs/specs/003-commission-closing/tasks.md"), None),
    ("edit-sensitive", tool("Edit", "commission/calculate.py"), None),
    ("edit-sensitive", tool("Edit", ".github/pull_request_template.md"), None),
]


@pytest.mark.parametrize(("rule_id", "decision", "payload", "branch"), POSITIVE)
def test_rule_fires_with_expected_decision(
    rule_id: str, decision: str, payload: dict[str, Any], branch: str | None
) -> None:
    result = guard.decide(payload, branch=branch)
    assert result is not None, f"expected {rule_id} to fire"
    assert (result.rule_id, result.decision) == (rule_id, decision)


@pytest.mark.parametrize(("rule_id", "payload", "branch"), NEGATIVE)
def test_near_miss_is_clean(rule_id: str, payload: dict[str, Any], branch: str | None) -> None:
    """Near misses must not be caught by any rule (keeps false positives low)."""
    result = guard.decide(payload, branch=branch)
    assert result is None, f"{rule_id} near miss was caught by {result}"


def test_every_rule_has_positive_and_negative_cases() -> None:
    ids = {r.id for r in guard.RULES} | {guard.PUSH_FROM_MAIN}
    assert ids - {r for r, _, _, _ in POSITIVE} == set(), "rules without a positive case"
    assert ids - {r for r, _, _ in NEGATIVE} == set(), "rules without a negative case"


def test_every_message_cites_its_source() -> None:
    """SPEC-010 §3.3: each denial explains itself and points to the ADR/SPEC."""
    missing = [r.id for r in guard.RULES if not re.search(r"(ADR|SPEC)-\d{3,4}", r.message)]
    assert missing == []


def test_deny_wins_over_ask() -> None:
    result = guard.decide(bash("databricks bundle deploy -t demo"), branch=T)
    assert result is not None and result.decision == guard.DENY


def test_unrelated_tools_are_ignored() -> None:
    assert guard.decide({"tool_name": "WebFetch", "tool_input": {"url": "https://x"}}) is None


def run_hook(stdin: str, python: str = sys.executable) -> dict[str, Any]:
    # Point the hook at a throwaway project dir so tests never write the real hooks.log.
    with tempfile.TemporaryDirectory() as tmp:
        out = subprocess.run(  # noqa: S603
            [python, str(GUARD_PATH)],
            input=stdin,
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
            env={**os.environ, "CLAUDE_PROJECT_DIR": tmp},
        )
    return json.loads(out.stdout) if out.stdout.strip() else {}


def test_cli_emits_deny_json() -> None:
    decision = run_hook(json.dumps(bash("gh pr merge 1")))["hookSpecificOutput"]
    assert decision["hookEventName"] == "PreToolUse"
    assert decision["permissionDecision"] == "deny"
    assert "ADR-0014" in decision["permissionDecisionReason"]


def test_cli_emits_nothing_when_no_objection() -> None:
    assert run_hook(json.dumps(bash("uv run pytest"))) == {}


@pytest.mark.parametrize("stdin", ["not json", "[]", json.dumps({"tool_name": "Bash"})])
def test_cli_fails_closed(stdin: str) -> None:
    output = run_hook(stdin)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_guard_source_is_python39_compatible() -> None:
    """The shebang may resolve to macOS /usr/bin/python3 (3.9). An import or syntax
    error there exits 1, which Claude Code treats as non-blocking (fail open)."""
    source = GUARD_PATH.read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 9))
    assert "from datetime import UTC" not in source


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="no system python3")
def test_guard_runs_under_system_python() -> None:
    decision = run_hook(json.dumps(bash("gh pr merge 1")), python="/usr/bin/python3")
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- settings.json (layer 1) -------------------------------------------------------

REQUIRED_DENY = {
    "Bash(gh pr merge*)",
    "Bash(git push origin main*)",
    "Bash(git push --force*)",
    "Bash(git push -f*)",
    "Bash(gh repo edit*)",
    "Bash(gh secret*)",
    "Bash(databricks bundle deploy -t demo*)",
    "Bash(gh auth token*)",
    "Bash(databricks auth token*)",
    "Bash(printenv*)",
    "Read(./.env)",
}
REQUIRED_ASK = {
    "Bash(databricks bundle deploy*)",
    "Bash(databricks jobs run-now*)",
    "Bash(uv run atlas-cli upload*)",
}
REQUIRED_ALLOW = {
    "Bash(uv run pytest*)",
    "Bash(uv run ruff *)",
    "Bash(uv run mypy*)",
    "Bash(git push -u origin task/*)",
    "Bash(gh pr create *)",
    "Bash(gh pr checks *)",
    "Bash(databricks bundle validate*)",
}


def test_settings_wire_the_guard_hook() -> None:
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    hooks = settings["hooks"]["PreToolUse"]
    commands = [h["command"] for entry in hooks for h in entry["hooks"]]
    assert any(".claude/hooks/guard.py" in c for c in commands)
    matchers = {m for entry in hooks for m in entry["matcher"].split("|")}
    expected = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Grep", "Glob"}
    assert expected <= matchers
    assert GUARD_PATH.stat().st_mode & 0o111, "guard.py must be executable"


def test_settings_permission_lists() -> None:
    perms = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))["permissions"]
    allow, ask, deny = set(perms["allow"]), set(perms["ask"]), set(perms["deny"])
    assert deny >= REQUIRED_DENY, REQUIRED_DENY - deny
    assert ask >= REQUIRED_ASK, REQUIRED_ASK - ask
    assert allow >= REQUIRED_ALLOW, REQUIRED_ALLOW - allow
    assert not allow & (ask | deny), "a rule cannot be both allowed and restricted"
    loose = [a for a in allow if re.search(r"merge|--force|-f\b|deploy|secret|token", a)]
    assert loose == [], f"allow list contains restricted actions: {loose}"
