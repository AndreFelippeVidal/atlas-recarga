#!/usr/bin/env python3
"""PreToolUse guard for the Claude Code harness (SPEC-010 §3-§4).

Layer 2 of 3: settings.json permission rules only match a Bash command as it was
written, so this hook inspects the *whole* command (``sh -c``, ``&&``, ``;``,
subshells, newlines). Each rule is matched against two views of the command:

- ``raw``: whitespace collapsed, newlines turned into ``;`` (segment boundaries kept)
- ``normalized``: additionally without quotes and without global options
  (``git -C . push`` -> ``git push``, ``gh -R o/r pr merge`` -> ``gh pr merge``)

Contract:
- stdin: hook JSON (``tool_name``, ``tool_input``, ``cwd``)
- no objection: exit 0, no stdout (normal permission flow applies)
- objection: exit 0 + ``hookSpecificOutput`` JSON with ``permissionDecision``
- internal error: **deny** (fail closed)

Stdlib only and **Python 3.9 compatible** (macOS ``/usr/bin/python3``): an import
error exits 1, which Claude Code treats as non-blocking, i.e. it would fail *open*.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

DENY = "deny"
ASK = "ask"

BASH_TOOLS = frozenset({"Bash"})
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
FILE_TOOLS = EDIT_TOOLS | READ_TOOLS

# Stays inside one shell segment, so a pattern cannot leak across `cmd1 && cmd2`.
_SEG = r"[^;&|\n]*"
_END = r"(?=$|[\s;&|)`'\"])"
_START = r"(?:^|[;&|(`'\"]\s*|\$\(\s*)"  # start of a (sub)command


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
MSG_FORCE = "Reescrita ou remoção de branch remota é proibida (SPEC-010 §3.3)."
MSG_REPO = "Configuração do repositório é do mantenedor (SPEC-010 §3.3)."
MSG_DEMO = "Deploy em demo é manual (ADR-0012)."
MSG_COMMISSION = "Aprovar comissão é decisão humana (ADR-0010)."
MSG_SECRET = "Segredos nunca passam pelo agente (SPEC-010 §3.3)."  # noqa: S105 (a message)
MSG_NO_VERIFY = "Os hooks de pre-commit não podem ser pulados (SPEC-010 §3.3)."
MSG_SPEC = "Mudar spec, ADR ou constituição é decisão humana: confirme (SPEC-010 §3.2)."
MSG_SENSITIVE = "Path sensível (comissão, semântica, harness ou CI): confirme (SPEC-010 §3.2)."
MSG_WORKSPACE = "Efeito no workspace Databricks: confirme (SPEC-010 §3.2)."

_GIT_PUSH = rf"\bgit\s+push\b{_SEG}"
_GH_API = r"\bgh\s+api\b"
_METHOD = r"(?:-X|--method)[\s=]*"
_WRITE_METHOD = rf"(?={_SEG}{_METHOD}(?:PATCH|PUT|DELETE)\b)"
_PUT = rf"(?={_SEG}{_METHOD}PUT\b)"

# Order matters: the first DENY wins; otherwise the first ASK wins.
RULES: list[Rule] = [
    # --- deny: merge ----------------------------------------------------------
    Rule("merge-pr", BASH_TOOLS, "command", _r(r"\bgh\s+pr\s+merge\b"), DENY, MSG_MERGE),
    Rule(
        "merge-api",
        BASH_TOOLS,
        "command",
        _r(
            rf"{_GH_API}{_PUT}{_SEG}/pulls/\d+/merge\b"
            rf"|{_GH_API}{_SEG}\brepos/[^/\s]+/[^/\s]+/merges\b"
            rf"|{_GH_API}\s+graphql\b{_SEG}\bmerge\w*PullRequest\b"
        ),
        DENY,
        MSG_MERGE,
    ),
    Rule(
        "gh-alias", BASH_TOOLS, "command", _r(r"\bgh\s+alias\s+(?:set|import)\b"), DENY, MSG_MERGE
    ),
    # --- deny: main and remote history ------------------------------------------
    Rule(
        "push-main",
        BASH_TOOLS,
        "command",
        _r(rf"{_GIT_PUSH}[\s:](?:refs/heads/)?main{_END}"),
        DENY,
        MSG_MAIN,
    ),
    Rule(
        "push-force",
        BASH_TOOLS,
        "command",
        _r(
            rf"{_GIT_PUSH}(?:\s--(?:force(?:-with-lease|-if-includes)?|delete|mirror|prune)\b"
            rf"|\s-[a-z]*[fd][a-z]*{_END}|\s\+\S|\s:\S)"
        ),
        DENY,
        MSG_FORCE,
    ),
    # --- deny: repository configuration -----------------------------------------
    Rule(
        "repo-protection",
        BASH_TOOLS,
        "command",
        _r(rf"{_GH_API}{_SEG}/(?:protection|rulesets)\b"),
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
        _r(rf"{_GH_API}{_WRITE_METHOD}{_SEG}\brepos/[^/\s]+/[^/\s]+/?{_END}"),
        DENY,
        MSG_REPO,
    ),
    Rule(
        "repo-graphql",
        BASH_TOOLS,
        "command",
        _r(
            rf"{_GH_API}\s+graphql\b{_SEG}"
            r"\b(?:update|delete|create)\w*(?:Repository|BranchProtectionRule|Ruleset)\b"
        ),
        DENY,
        MSG_REPO,
    ),
    # --- deny: Databricks ---------------------------------------------------------
    Rule(
        "deploy-demo",
        BASH_TOOLS,
        "command",
        _r(rf"\bbundle\s+deploy\b{_SEG}(?:-t|--target)[\s=]*demo\b"),
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
    # --- deny: secrets --------------------------------------------------------------
    Rule(
        "secret-file-cmd",
        BASH_TOOLS,
        "command",
        _r(
            r"(?:^|[\s/'\"=<])(?:\.env(?:\.(?!example\b)[\w.-]+)?|\.databrickscfg|[\w.-]+\.(?:pem|key))"
            r"(?=$|[\s'\";|&)>*])"
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
        _r(
            r"\bprintenv\b"
            rf"|{_START}(?:env(?:\s+-0)?|export(?:\s+-p)?|set|declare\s+-[a-z]*x[a-z]*)"
            r"\s*(?=$|[;&|)`'\"])"  # the whole (sub)command, not `env FOO=1 cmd`
        ),
        DENY,
        MSG_SECRET,
    ),
    # --- deny: skipping local hooks -------------------------------------------------
    Rule(
        "no-verify",
        BASH_TOOLS,
        "command",
        _r(
            rf"\bgit\s+(?:commit|push)\b{_SEG}\s--no-verify\b"
            rf"|\bgit\s+commit\b{_SEG}\s-[aqvsSeupm]*n[aqvsSeupm]*{_END}"
            r"|\bcore\.hooksPath\b|(?:^|[\s;&|])SKIP="
        ),
        DENY,
        MSG_NO_VERIFY,
    ),
    # --- deny: file tools -----------------------------------------------------------
    Rule(
        "secret-file-path",
        FILE_TOOLS,
        "path",
        _r(r"(?:^|/)(?:\.env(?:\.(?!example$)[\w.-]+)?|\.databrickscfg|[\w.-]+\.(?:pem|key))$"),
        DENY,
        MSG_SECRET,
        sensitive=True,
    ),
    # --- ask: Bash ------------------------------------------------------------------
    Rule("deploy", BASH_TOOLS, "command", _r(r"\bbundle\s+deploy\b"), ASK, MSG_WORKSPACE),
    Rule(
        "workspace-write",
        BASH_TOOLS,
        "command",
        _r(
            r"\bdatabricks\s+(?:fs\s+(?:cp|rm|mv)|jobs\s+run-now|pipelines\s+start-update)\b"
            r"|\batlas-cli\s+upload\b"
        ),
        ASK,
        MSG_WORKSPACE,
    ),
    # --- ask: edit tools ------------------------------------------------------------
    Rule(
        "edit-spec",
        EDIT_TOOLS,
        "path",
        _r(r"^docs/(?:specs/(?:.+/spec\.md|mission\.md|tech-stack\.md)|adr/.+)$"),
        ASK,
        MSG_SPEC,
    ),
    Rule(
        "edit-sensitive",
        EDIT_TOOLS,
        "path",
        _r(
            r"^(?:commission/(?:rules\.py|.+\.ya?ml)|semantic/.+|\.claude/.+"
            r"|\.github/(?:workflows/.+|CODEOWNERS))$"
        ),
        ASK,
        MSG_SENSITIVE,
    ),
]

PUSH_FROM_MAIN = "push-from-main"
GUARD_ERROR = "guard-error"

# Global options that may sit between the program and its subcommand.
_GIT_GLOBALS = re.compile(
    r"\bgit((?:\s+(?:-C|-c|--git-dir|--work-tree|--namespace|--exec-path)(?:=|\s+)\S+"
    r"|\s+--?[a-z][\w-]*)+)(?=\s+[a-z])",
    re.IGNORECASE,
)
_GH_GLOBALS = re.compile(r"\bgh((?:\s+(?:-R|--repo)(?:=|\s+)\S+)+)(?=\s+[a-z])", re.IGNORECASE)
_PUSH_SEGMENT = re.compile(rf"\bgit\s+push\b{_SEG}", re.IGNORECASE)


def flatten(command: str) -> str:
    """Collapse whitespace but keep newlines as segment boundaries."""
    return " ".join(command.replace("\r", "\n").replace("\n", " ; ").split())


def normalize(command: str) -> str:
    """Flatten, drop quotes and global options so subcommand rules still match."""
    flat = flatten(command).replace('"', "").replace("'", "")
    flat = _GIT_GLOBALS.sub("git", flat)
    return _GH_GLOBALS.sub("gh", flat)


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


def _file_targets(tool: str, tool_input: dict[str, Any], root: Path) -> list[str]:
    if tool in ("Grep", "Glob"):
        raw = tool_input.get("path")
        return [relative_path(raw, root)] if isinstance(raw, str) and raw else []
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(raw, str):
        raise ValueError(f"{tool} payload without file path")
    return [relative_path(raw, root)]


def decide(payload: dict[str, Any], branch: str | None = None) -> Decision | None:
    """Pure decision function (no I/O except an optional `git` lookup)."""
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        raise ValueError("malformed hook payload")
    root = project_root(payload)

    texts: dict[str, list[str]] = {}
    if tool in BASH_TOOLS:
        command = tool_input.get("command")
        if not isinstance(command, str):
            raise ValueError("Bash payload without command")
        texts["command"] = [flatten(command), normalize(command)]
    elif tool in FILE_TOOLS:
        texts["path"] = _file_targets(tool, tool_input, root)
    else:
        return None

    asks: list[Decision] = []
    for rule in RULES:
        if tool not in rule.tools or rule.target not in texts:
            continue
        if any(rule.pattern.search(text) for text in texts[rule.target]):
            hit = Decision(rule.decision, rule.id, rule.message, rule.sensitive)
            if rule.decision == DENY:
                return hit
            asks.append(hit)

    # A push with no explicit task/* target pushes the current branch: deny it on main.
    for segment in _PUSH_SEGMENT.findall(texts.get("command", ["", ""])[1]):
        if not re.search(r"\btask/\S+", segment):
            on_branch = branch if branch is not None else current_branch(root)
            if on_branch == "main":
                return Decision(DENY, PUSH_FROM_MAIN, MSG_MAIN)

    return asks[0] if asks else None


def log(root: Path, tool: str, result: Decision, detail: str) -> None:
    try:
        line = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017 (3.9)
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
        detail = str(
            tool_input.get("command") or tool_input.get("file_path") or tool_input.get("path") or ""
        )
        log(project_root(payload), str(payload.get("tool_name")), result, detail)
        emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
