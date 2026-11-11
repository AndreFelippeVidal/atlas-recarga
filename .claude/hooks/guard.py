#!/usr/bin/env python3
"""PreToolUse guard for the Claude Code harness (SPEC-010 §3-§4).

Layer 2 of 3: settings.json permission rules only match a Bash command as it was
written, so this hook inspects the *whole* command (``sh -c``, ``&&``, ``;``,
subshells) and the target path of file tools, and returns ``deny`` or ``ask``.

Contract:
- stdin: hook JSON (``tool_name``, ``tool_input``, ``cwd``)
- no objection: exit 0, no stdout (normal permission flow applies)
- objection: exit 0 + ``hookSpecificOutput`` JSON with ``permissionDecision``
- internal error: **deny** (fail closed)

Stdlib only, so it starts fast and needs no virtualenv.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

DENY = "deny"
ASK = "ask"

BASH_TOOLS = frozenset({"Bash"})
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
READ_TOOLS = frozenset({"Read"})
FILE_TOOLS = EDIT_TOOLS | READ_TOOLS

# A shell "segment" boundary, so a pattern cannot leak across `cmd1 && cmd2`.
_SEG = r"[^;&|\n]*"


class Rule(NamedTuple):
    id: str
    tools: frozenset[str]
    target: str  # "command" | "path"
    pattern: re.Pattern[str]
    decision: str
    message: str
    sensitive: bool = False  # never log the raw command/path


def _r(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


MSG_MERGE = "Merge é do mantenedor (ADR-0014). Peça a revisão no PR."
MSG_MAIN = "A main só muda por PR (SPEC-009 §5)."
MSG_FORCE = "Reescrita de histórico remoto é proibida (SPEC-010 §3.3)."
MSG_REPO = "Configuração do repositório é do mantenedor (SPEC-010 §3.3)."
MSG_DEMO = "Deploy em demo é manual (ADR-0012)."
MSG_COMMISSION = "Aprovar comissão é decisão humana (ADR-0010)."
MSG_SECRET = "Segredos nunca passam pelo agente (SPEC-010 §3.3)."  # noqa: S105 (a message, not a secret)
MSG_NO_VERIFY = "Os hooks de pre-commit não podem ser pulados (SPEC-010 §3.3)."
MSG_SPEC = "Mudar spec, ADR ou constituição é decisão humana: confirme (SPEC-010 §3.2)."
MSG_SENSITIVE = "Path sensível (comissão, semântica, harness ou CI): confirme (SPEC-010 §3.2)."
MSG_WORKSPACE = "Efeito no workspace Databricks: confirme (SPEC-010 §3.2)."

# Order matters: the first DENY wins; otherwise the first ASK wins.
RULES: list[Rule] = [
    # --- deny: Bash -----------------------------------------------------------
    Rule("merge-pr", BASH_TOOLS, "command", _r(r"\bgh\s+pr\s+merge\b"), DENY, MSG_MERGE),
    Rule("merge-api", BASH_TOOLS, "command", _r(rf"\bgh\s+api\b{_SEG}/merge\b"), DENY, MSG_MERGE),
    Rule(
        "push-main",
        BASH_TOOLS,
        "command",
        _r(rf"\bgit\s+push\b{_SEG}[\s:](?:refs/heads/)?main(?=$|[\s;&|])"),
        DENY,
        MSG_MAIN,
    ),
    Rule(
        "push-force",
        BASH_TOOLS,
        "command",
        _r(rf"\bgit\s+push\b{_SEG}(?:\s--force(?:-with-lease)?\b|\s-f\b|\s\+\S|\s--delete\b)"),
        DENY,
        MSG_FORCE,
    ),
    Rule(
        "repo-protection",
        BASH_TOOLS,
        "command",
        _r(rf"\bgh\s+api\b{_SEG}/(?:protection|rulesets)\b"),
        DENY,
        MSG_REPO,
    ),
    Rule(
        "repo-settings",
        BASH_TOOLS,
        "command",
        _r(r"\bgh\s+(?:repo\s+(?:edit|delete|rename|archive)|secret|ruleset|variable)\b"),
        DENY,
        MSG_REPO,
    ),
    Rule(
        "repo-patch",
        BASH_TOOLS,
        "command",
        _r(
            rf"\bgh\s+api\b{_SEG}(?:-X|--method)\s*(?:PATCH|PUT|DELETE)\b{_SEG}\brepos/[^/\s]+/[^/\s]+/?(?=$|\s)"
        ),
        DENY,
        MSG_REPO,
    ),
    Rule(
        "deploy-demo",
        BASH_TOOLS,
        "command",
        _r(rf"\bbundle\s+deploy\b{_SEG}(?:-t|--target)[\s=]+demo\b"),
        DENY,
        MSG_DEMO,
    ),
    Rule(
        "commission-review",
        BASH_TOOLS,
        "command",
        _r(rf"\b(?:databricks|run-now)\b{_SEG}commission_review\b"),
        DENY,
        MSG_COMMISSION,
    ),
    Rule(
        "secret-file-cmd",
        BASH_TOOLS,
        "command",
        _r(
            r"(?:^|[\s/'\"=<])(?:\.env(?:\.(?!example\b)[\w.-]+)?|\.databrickscfg|[\w.-]+\.(?:pem|key))"
            r"(?=$|[\s'\";|&)>])"
        ),
        DENY,
        MSG_SECRET,
        sensitive=True,
    ),
    Rule(
        "secret-token-cmd",
        BASH_TOOLS,
        "command",
        _r(r"\b(?:gh|databricks)\s+auth\s+token\b"),
        DENY,
        MSG_SECRET,
        sensitive=True,
    ),
    Rule(
        "dump-env",
        BASH_TOOLS,
        "command",
        _r(r"(?:^|[;&|]\s*)(?:printenv|env|export\s+-p|set)\s*(?=$|[;&|])"),
        DENY,
        MSG_SECRET,
    ),
    Rule(
        "no-verify",
        BASH_TOOLS,
        "command",
        _r(rf"\bgit\s+(?:commit|push)\b{_SEG}\s--no-verify\b"),
        DENY,
        MSG_NO_VERIFY,
    ),
    # --- deny: file tools -----------------------------------------------------
    Rule(
        "secret-file-path",
        FILE_TOOLS,
        "path",
        _r(r"(?:^|/)(?:\.env(?:\.(?!example$)[\w.-]+)?|\.databrickscfg|[\w.-]+\.(?:pem|key))$"),
        DENY,
        MSG_SECRET,
        sensitive=True,
    ),
    # --- ask: Bash ------------------------------------------------------------
    Rule("deploy", BASH_TOOLS, "command", _r(r"\bbundle\s+deploy\b"), ASK, MSG_WORKSPACE),
    Rule(
        "workspace-write",
        BASH_TOOLS,
        "command",
        _r(
            r"\bdatabricks\s+(?:fs\s+(?:cp|rm|mv)|jobs\s+run-now|pipelines\s+start-update)\b|\batlas-cli\s+upload\b"
        ),
        ASK,
        MSG_WORKSPACE,
    ),
    # --- ask: edit tools ------------------------------------------------------
    Rule(
        "edit-spec",
        EDIT_TOOLS,
        "path",
        _r(r"^docs/(?:specs/(?:[^/]+/spec\.md|mission\.md|tech-stack\.md)|adr/.+)$"),
        ASK,
        MSG_SPEC,
    ),
    Rule(
        "edit-sensitive",
        EDIT_TOOLS,
        "path",
        _r(
            r"^(?:commission/(?:rules\.py|.+\.ya?ml)|semantic/.+|\.claude/.+|\.github/(?:workflows/.+|CODEOWNERS))$"
        ),
        ASK,
        MSG_SENSITIVE,
    ),
]

PUSH_FROM_MAIN = "push-from-main"
GUARD_ERROR = "guard-error"


class Decision(NamedTuple):
    decision: str
    rule_id: str
    message: str
    sensitive: bool = False


def project_root(payload: dict[str, Any]) -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    return Path(root).resolve()


def relative_path(raw: str, root: Path) -> str:
    """Repo-relative POSIX path; absolute path unchanged if outside the repo."""
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    resolved = Path(os.path.normpath(path))
    try:
        return PurePosixPath(resolved.relative_to(root)).as_posix()
    except ValueError:
        return resolved.as_posix()


def current_branch(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def decide(payload: dict[str, Any], branch: str | None = None) -> Decision | None:
    """Pure decision function (no I/O except an optional `git` lookup)."""
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        raise ValueError("malformed hook payload")
    root = project_root(payload)

    targets: dict[str, str] = {}
    if tool in BASH_TOOLS:
        command = tool_input.get("command")
        if not isinstance(command, str):
            raise ValueError("Bash payload without command")
        targets["command"] = " ".join(command.split())
    elif tool in FILE_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not isinstance(raw, str):
            raise ValueError(f"{tool} payload without file path")
        targets["path"] = relative_path(raw, root)
    else:
        return None

    asks: list[Decision] = []
    for rule in RULES:
        if tool not in rule.tools or rule.target not in targets:
            continue
        if rule.pattern.search(targets[rule.target]):
            hit = Decision(rule.decision, rule.id, rule.message, rule.sensitive)
            if rule.decision == DENY:
                return hit
            asks.append(hit)

    command = targets.get("command", "")
    if re.search(r"\bgit\s+push\b", command) and not re.search(r"\btask/\S+", command):
        on_branch = branch if branch is not None else current_branch(root)
        if on_branch == "main":
            return Decision(DENY, PUSH_FROM_MAIN, MSG_MAIN)

    return asks[0] if asks else None


def log(root: Path, tool: str, result: Decision, detail: str) -> None:
    try:
        line = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "tool": tool,
            "decision": result.decision,
            "rule": result.rule_id,
            "detail": "<redacted>" if result.sensitive else detail[:200],
        }
        with (root / ".claude" / "hooks.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass  # logging must never change the decision


def emit(result: Decision) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": result.decision,
                    "permissionDecisionReason": result.message,
                }
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
        result = decide(payload)
    except Exception as exc:  # fail closed
        emit(Decision(DENY, GUARD_ERROR, f"guard.py falhou ({type(exc).__name__}); revise o log."))
        return 0
    if result is not None:
        tool_input = payload.get("tool_input") or {}
        detail = str(tool_input.get("command") or tool_input.get("file_path") or "")
        log(project_root(payload), str(payload.get("tool_name")), result, detail)
        emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
