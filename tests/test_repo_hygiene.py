"""Repository hygiene and SDD consistency checks (SPEC-009 §6)."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS = ROOT / "docs" / "specs"
ADRS = ROOT / "docs" / "adr"
ROADMAP = SPECS / "roadmap.md"

TASK_ID = re.compile(r"^- \[[ x]\] \*\*(P\d+\.\d+)\*\*", re.MULTILINE)
TASKS_MD_ID = re.compile(r"^### (P\d+\.\d+)\b", re.MULTILINE)
PHASE_HEADING = re.compile(r"^## Fase \d+ — .*$", re.MULTILINE)

FORBIDDEN_PATTERNS = [".env", ".env.*", "*.pem", "*.key", "*token*", ".databrickscfg"]
ALLOWED_EXCEPTIONS = {".env.example"}

REQUIRED_FILES = [
    "README.md",
    ".gitignore",
    ".editorconfig",
    "CONTRIBUTING.md",
    ".github/pull_request_template.md",
    ".github/CODEOWNERS",
    "CLAUDE.md",
]


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"],  # noqa: S607
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return out.stdout.splitlines()


def roadmap_phases() -> list[tuple[str, str]]:
    """Return (heading, body) for each phase section of the roadmap."""
    text = ROADMAP.read_text(encoding="utf-8")
    headings = list(PHASE_HEADING.finditer(text))
    phases = []
    for i, h in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else text.find("\n## ", h.end())
        body = text[h.end() : end if end != -1 else len(text)]
        phases.append((h.group(0), body))
    return phases


def test_no_secret_like_files_are_tracked() -> None:
    offenders = [
        f
        for f in tracked_files()
        if Path(f).name not in ALLOWED_EXCEPTIONS
        and any(fnmatch.fnmatch(Path(f).name.lower(), p) for p in FORBIDDEN_PATTERNS)
    ]
    assert offenders == [], f"secret-like files tracked: {offenders}"


def test_required_files_exist() -> None:
    missing = [f for f in REQUIRED_FILES if not (ROOT / f).is_file()]
    assert missing == [], f"missing required files: {missing}"


def test_every_spec_folder_has_spec_and_tasks() -> None:
    folders = [p for p in SPECS.iterdir() if p.is_dir() and re.match(r"\d{3}-", p.name)]
    assert folders, "no spec folders found"
    incomplete = [
        p.name for p in folders if not (p / "spec.md").is_file() or not (p / "tasks.md").is_file()
    ]
    assert incomplete == [], f"spec folders missing spec.md/tasks.md: {incomplete}"


def test_roadmap_task_ids_are_unique() -> None:
    ids = TASK_ID.findall(ROADMAP.read_text(encoding="utf-8"))
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert duplicates == [], f"duplicate task ids in roadmap: {duplicates}"


def test_roadmap_and_tasks_md_are_in_sync() -> None:
    in_tasks_md: set[str] = set()
    for tasks in SPECS.glob("*/tasks.md"):
        in_tasks_md |= set(TASKS_MD_ID.findall(tasks.read_text(encoding="utf-8")))

    in_roadmap_with_spec: set[str] = set()
    for heading, body in roadmap_phases():
        if "→ [" in heading:  # phases without a spec (e.g. release) are exempt
            in_roadmap_with_spec |= set(TASK_ID.findall(body))

    assert in_roadmap_with_spec - in_tasks_md == set(), "roadmap tasks missing from tasks.md"
    assert in_tasks_md - in_roadmap_with_spec == set(), "tasks.md entries missing from roadmap"


def test_done_tasks_reference_a_pr_or_commit() -> None:
    reference = re.compile(r"\(#\d+\)|\([0-9a-f]{7,40}[;)]")
    unreferenced = [
        TASK_ID.search(line).group(1)  # type: ignore[union-attr]
        for line in ROADMAP.read_text(encoding="utf-8").splitlines()
        if line.startswith("- [x]") and not reference.search(line)
    ]
    assert unreferenced == [], f"done tasks without PR/commit reference: {unreferenced}"


def test_adrs_have_status_and_at_least_two_options() -> None:
    problems = []
    for adr in sorted(ADRS.glob("[0-9][0-9][0-9][0-9]-*.md")):
        if adr.name.startswith("0000-"):
            continue
        text = adr.read_text(encoding="utf-8")
        if "**Status:**" not in text:
            problems.append(f"{adr.name}: no Status")
        section = text.split("## Opções consideradas", 1)
        options = (
            re.findall(r"^\d+\. ", section[1].split("\n## ", 1)[0], re.MULTILINE)
            if len(section) == 2
            else []
        )
        if len(options) < 2:
            problems.append(f"{adr.name}: fewer than 2 options")
    assert problems == [], problems


def test_claude_md_stays_short() -> None:
    """SPEC-010 §5: CLAUDE.md points to the constitution instead of duplicating it."""
    lines = (ROOT / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 150, f"CLAUDE.md has {len(lines)} lines (max 150)"


def test_architecture_covers_every_prd_capability() -> None:
    """SPEC-011 §3: every PRD capability and its spec appear in docs/architecture.md."""
    prd = (ROOT / "docs" / "prd.md").read_text(encoding="utf-8")
    arch = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    capabilities = re.findall(r"^\| (F\d+) \|.*?\(specs/(\d{3}-[a-z0-9-]+)/spec\.md\)", prd, re.M)
    assert capabilities, "no F<n> rows found in the PRD scope table"
    missing = [
        f"{cap} ({spec})"
        for cap, spec in capabilities
        if f"| {cap} |" not in arch or f"specs/{spec}/spec.md" not in arch
    ]
    assert missing == [], f"architecture.md is missing: {missing}"


def test_architecture_lists_every_catalog_schema() -> None:
    """SPEC-011 §4: each schema from ADR-0003 has a row in "Onde ficam os dados"."""
    adr = (ADRS / "0003-medallion-unity-catalog.md").read_text(encoding="utf-8")
    arch = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    listed = re.search(r"schemas por camada e propósito:\*\* `([^`]+)`", adr)
    assert listed, "schema list not found in ADR-0003"
    schemas = [s.strip() for s in listed.group(1).split(",")]
    missing = [s for s in schemas if f"| `{s}` |" not in arch]
    assert missing == [], f"architecture.md has no row for: {missing}"
