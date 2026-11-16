"""Idempotent workspace setup: catalog, schemas, Volume and groups (SPEC-002 §2, task P5.2).

Run by the **maintainer** against the workspace (the agent only prepares it). Every
statement is `IF NOT EXISTS`, and groups are created only when missing, so it is safe to
run again. It uses the Databricks CLI (no extra dependency) and never touches secrets.

    uv run python scripts/setup_workspace.py --target dev --profile andrevidal --dry-run
    uv run python scripts/setup_workspace.py --target dev --profile andrevidal

Targets mirror `databricks.yml`: `dev` -> catalog `atlas_dev`, `demo` -> catalog `atlas`.
Schemas follow ADR-0003. Grants (P7.3, SPEC-004 §7): `atlas_readers` gets `USE CATALOG` and
`USE SCHEMA` + `SELECT` on `semantic` only, nothing on gold/silver/bronze/commission. The
`commission` grants come with SPEC-003. Grants need the group to exist, so they run after it.
Membership (P8.6): `--analyst` / `--director` (repeatable, user e-mails) add people to
`atlas_commission_analysts` / `atlas_commission_directors`, which `atlas_commission_review`
reads to decide who may approve (SPEC-003 §4). Idempotent; nobody is added without the flag.
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
READERS_GROUP = "atlas_readers"
ANALYSTS_GROUP = "atlas_commission_analysts"
DIRECTORS_GROUP = "atlas_commission_directors"
ALREADY_EXISTS = ("already exists", "already in use", "conflict")
MAX_POLLS = 90  # ~3 min at 2 s; a stuck statement fails instead of hanging
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


_PRINCIPAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]*$")  # user e-mail, SP name or application id


def build_grant_statements(catalog: str, readers: Sequence[str] = ()) -> list[str]:
    """Grants of the readers: the metric views are the only read door (SPEC-004 §7).

    `atlas_readers` is a workspace group, which Unity Catalog does not evaluate (ADR-0016), so
    each reader principal also gets the grants directly. Names are validated, never free SQL.
    """
    if not _IDENTIFIER.fullmatch(catalog):
        raise ValueError(f"invalid catalog name: {catalog!r}")
    statements = []
    for principal in (READERS_GROUP, *readers):
        if principal != READERS_GROUP and not _PRINCIPAL.fullmatch(principal):
            raise ValueError(f"invalid principal: {principal!r}")
        statements += [
            f"GRANT USE CATALOG ON CATALOG {catalog} TO `{principal}`",
            f"GRANT USE SCHEMA, SELECT ON SCHEMA {catalog}.semantic TO `{principal}`",
            # as fn_* do agente (SPEC-005 §3): EXECUTE, nada além de semantic
            f"GRANT EXECUTE ON SCHEMA {catalog}.semantic TO `{principal}`",
        ]
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
    for _ in range(MAX_POLLS):
        if not (
            isinstance(response, dict)
            and response.get("status", {}).get("state") in ("PENDING", "RUNNING")
        ):
            break
        time.sleep(2)
        statement_id = response.get("statement_id")
        if not statement_id:
            raise RuntimeError(f"no statement_id in the response for {statement!r}")
        response = _cli(profile, ["api", "get", f"/api/2.0/sql/statements/{statement_id}"])
    state = response.get("status", {}) if isinstance(response, dict) else {}
    if state.get("state") in ("PENDING", "RUNNING"):
        raise RuntimeError(
            f"timed out waiting for {statement!r}; it may still finish on the warehouse. "
            "Check the query history, then run the script again (it is idempotent)."
        )
    if state.get("state") != "SUCCEEDED":
        raise RuntimeError(f"statement failed: {statement!r} -> {state}")


def _ensure_groups(profile: str) -> list[str]:
    existing = _cli(profile, ["groups", "list"])
    names = {g.get("displayName") for g in existing or [] if isinstance(g, dict)}
    created = []
    for group in GROUPS:
        if group not in names:
            try:
                _cli(profile, ["groups", "create"], {"displayName": group})
            except RuntimeError as error:
                # `groups list` is paginated, so the group may exist without being listed
                if not any(marker in str(error).lower() for marker in ALREADY_EXISTS):
                    raise
                continue
            created.append(group)
    return created


_USER_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")  # goes into a SCIM filter


def _one(items: Any, what: str) -> dict[str, Any]:
    found = [i for i in items or [] if isinstance(i, dict)]
    if len(found) != 1:
        raise RuntimeError(f"expected exactly one {what}, found {len(found)}")
    return found[0]


def ensure_members(profile: str, group: str, users: Sequence[str]) -> list[str]:
    """Add each user (e-mail) to `group` unless already a member; return the ones added."""
    if not users:
        return []
    if group not in (ANALYSTS_GROUP, DIRECTORS_GROUP):
        raise ValueError(f"membership is only managed for the commission groups, not {group!r}")
    for user in users:
        if not _USER_EMAIL.fullmatch(user):
            raise ValueError(f"invalid user e-mail: {user!r}")
    group_ref = _one(
        _cli(profile, ["groups", "list", "--filter", f'displayName eq "{group}"']), f"group {group}"
    )
    current = _cli(profile, ["groups", "get", str(group_ref["id"])]) or {}
    member_ids = {str(m.get("value")) for m in current.get("members", []) if isinstance(m, dict)}
    added = []
    for user in users:
        user_ref = _one(
            _cli(profile, ["users", "list", "--filter", f'userName eq "{user}"']), f"user {user}"
        )
        if str(user_ref["id"]) in member_ids:
            continue
        operations = [{"op": "add", "value": {"members": [{"value": str(user_ref["id"])}]}}]
        _cli(profile, ["groups", "patch", str(group_ref["id"])], {"Operations": operations})
        added.append(user)
    return added


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="Databricks CLI profile (never implicit)")
    parser.add_argument("--warehouse-id", help="SQL warehouse; auto-picked if there is only one")
    parser.add_argument(
        "--reader",
        action="append",
        default=[],
        help="principal (user e-mail, SP name or application id) that reads `semantic`; repeatable",
    )
    parser.add_argument(
        "--analyst",
        action="append",
        default=[],
        help=f"user e-mail added to {ANALYSTS_GROUP} (may approve as analyst); repeatable",
    )
    parser.add_argument(
        "--director",
        action="append",
        default=[],
        help=f"user e-mail added to {DIRECTORS_GROUP} (may approve as director); repeatable",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the plan and change nothing")
    args = parser.parse_args(argv)

    statements = build_statements(CATALOGS[args.target])
    if args.dry_run:
        print("\n".join(f"{s};" for s in statements))
        print("\n".join(f"-- group (created if missing): {g}" for g in GROUPS))
        print("\n".join(f"-- member of {ANALYSTS_GROUP}: {u}" for u in args.analyst))
        print("\n".join(f"-- member of {DIRECTORS_GROUP}: {u}" for u in args.director))
        grants = build_grant_statements(CATALOGS[args.target], args.reader)
        print("\n".join(f"{s};" for s in grants))
        return 0

    warehouse_id = _pick_warehouse(args.profile, args.warehouse_id)
    for statement in statements:
        _run_sql(args.profile, warehouse_id, statement)
        print(f"ok: {statement.split(' COMMENT')[0]}")
    created = _ensure_groups(args.profile)
    print(f"groups created: {', '.join(created) or 'none (already existed)'}")
    for group, users in ((ANALYSTS_GROUP, args.analyst), (DIRECTORS_GROUP, args.director)):
        added = ensure_members(args.profile, group, users)
        if users:
            print(f"{group}: added {', '.join(added) or 'none (already members)'}")
    for statement in build_grant_statements(CATALOGS[args.target], args.reader):
        _run_sql(args.profile, warehouse_id, statement)  # GRANT is idempotent in Unity Catalog
        print(f"ok: {statement}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
