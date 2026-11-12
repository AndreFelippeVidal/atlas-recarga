"""Idempotent workspace setup: catalog, schemas, Volume and groups (SPEC-002 §2, task P5.2).

Run by the **maintainer** against the workspace (the agent only prepares it). Every
statement is `IF NOT EXISTS`, and groups are created only when missing, so it is safe to
run again. It uses the Databricks CLI (no extra dependency) and never touches secrets.

    uv run python scripts/setup_workspace.py --target dev --profile andrevidal --dry-run
    uv run python scripts/setup_workspace.py --target dev --profile andrevidal

Targets mirror `databricks.yml`: `dev` -> catalog `atlas_dev`, `demo` -> catalog `atlas`.
Schemas follow ADR-0003. Grants are NOT part of this task: `atlas_readers` gets `SELECT` on
`semantic` in P7.3, and the `commission` grants come with SPEC-003.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # the Databricks CLI is the only thing we call
import sys
import time
from collections.abc import Mapping, Sequence
from typing import Any

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # keep in sync with databricks.yml
SCHEMAS = (
    "raw",
    "bronze",
    "silver",
    "gold",
    "semantic",
    "commission",
    "eval",
    "observability",
)
VOLUME_SCHEMA = "raw"
VOLUME_NAME = "landing"
GROUPS = ("atlas_readers", "atlas_commission_analysts", "atlas_commission_directors")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


def build_statements(catalog: str) -> list[str]:
    """Return the setup SQL. Only closed lists and a validated identifier go in (no free SQL)."""
    if not _IDENTIFIER.fullmatch(catalog):
        raise ValueError(f"invalid catalog name: {catalog!r}")
    statements = [f"CREATE CATALOG IF NOT EXISTS {catalog}"]
    statements += [f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}" for schema in SCHEMAS]
    statements.append(
        f"CREATE VOLUME IF NOT EXISTS {catalog}.{VOLUME_SCHEMA}.{VOLUME_NAME} "
        "COMMENT 'Landing dos arquivos sintéticos (SPEC-001); fonte imutável do pipeline'"
    )
    return statements


def _cli(profile: str, args: Sequence[str], body: Mapping[str, object] | None = None) -> Any:
    command = ["databricks", "--profile", profile, *args, "-o", "json"]
    if body is not None:
        command += ["--json", json.dumps(body)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"`databricks {' '.join(args)}` failed: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def _pick_warehouse(profile: str, warehouse_id: str | None) -> str:
    if warehouse_id:
        return warehouse_id
    warehouses = _cli(profile, ["warehouses", "list"])
    ids = [w["id"] for w in warehouses or [] if isinstance(w, dict)]
    if len(ids) != 1:
        raise RuntimeError(f"found {len(ids)} SQL warehouses; pass --warehouse-id explicitly")
    return str(ids[0])


def _run_sql(profile: str, warehouse_id: str, statement: str) -> None:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    response = _cli(profile, ["api", "post", "/api/2.0/sql/statements"], body)
    while isinstance(response, dict) and response.get("status", {}).get("state") in (
        "PENDING",
        "RUNNING",
    ):
        time.sleep(2)
        response = _cli(
            profile, ["api", "get", f"/api/2.0/sql/statements/{response['statement_id']}"]
        )
    state = response.get("status", {}) if isinstance(response, dict) else {}
    if state.get("state") != "SUCCEEDED":
        raise RuntimeError(f"statement failed: {statement!r} -> {state}")


def _ensure_groups(profile: str) -> list[str]:
    existing = _cli(profile, ["groups", "list"])
    names = {g.get("displayName") for g in existing or [] if isinstance(g, dict)}
    created = []
    for group in GROUPS:
        if group not in names:
            _cli(profile, ["groups", "create"], {"displayName": group})
            created.append(group)
    return created


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="Databricks CLI profile (never implicit)")
    parser.add_argument("--warehouse-id", help="SQL warehouse; auto-picked if there is only one")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and change nothing")
    args = parser.parse_args(argv)

    statements = build_statements(CATALOGS[args.target])
    if args.dry_run:
        print("\n".join(f"{s};" for s in statements))
        print("\n".join(f"-- group (created if missing): {g}" for g in GROUPS))
        return 0

    warehouse_id = _pick_warehouse(args.profile, args.warehouse_id)
    for statement in statements:
        _run_sql(args.profile, warehouse_id, statement)
        print(f"ok: {statement.split(' COMMENT')[0]}")
    created = _ensure_groups(args.profile)
    print(f"groups created: {', '.join(created) or 'none (already existed)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
