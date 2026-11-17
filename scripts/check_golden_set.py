"""Confere `eval/golden_set.yaml` (SPEC-008 §3, task P9.1).

Toda `reference_sql` deve executar e devolver 1 valor; a `reference_month_sql` (casos
`no_period`) devolve 1 data `AAAA-MM-DD`.

As views só existem no workspace, então o **mantenedor** roda este script no `dev`:

    uv run python scripts/check_golden_set.py --target dev --profile andrevidal \\
        --warehouse-id <id>

Só lê. Falha (saída 1) se alguma `reference_sql` não executar, não devolver exatamente 1 linha
com 1 coluna ou devolver um valor nulo ou não numérico.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
GOLDEN_SET = Path(__file__).resolve().parents[1] / "eval" / "golden_set.yaml"


def load_cases(path: Path = GOLDEN_SET) -> list[dict[str, Any]]:
    return list(yaml.safe_load(path.read_text(encoding="utf-8")))


def for_catalog(sql: str, catalog: str) -> str:
    """A SQL do golden set usa o catálogo `atlas`; no `dev` o catálogo é `atlas_dev`."""
    return sql.replace("atlas.semantic.", f"{catalog}.semantic.")


def check_value(case_id: str, rows: Sequence[Sequence[str | None]]) -> str:
    """Uma linha de relatório por caso: `ok ...` ou `FALHA ...`."""
    if len(rows) != 1 or len(rows[0]) != 1:
        shape = f"{len(rows)} linha(s)" + (f" x {len(rows[0])} coluna(s)" if rows else "")
        return f"FALHA {case_id}: esperava 1 valor, veio {shape}"
    raw = rows[0][0]
    try:
        value = Decimal(raw) if raw is not None else None
    except InvalidOperation:
        value = None
    if value is None:
        return f"FALHA {case_id}: valor nulo ou não numérico ({raw!r})"
    return f"ok    {case_id}: {value}"


def check_month(case_id: str, rows: Sequence[Sequence[str | None]]) -> str:
    """Como `check_value`, para a `reference_month_sql`: uma data `AAAA-MM-DD`."""
    if len(rows) != 1 or len(rows[0]) != 1:
        shape = f"{len(rows)} linha(s)" + (f" x {len(rows[0])} coluna(s)" if rows else "")
        return f"FALHA {case_id}: mês: esperava 1 valor, veio {shape}"
    raw = rows[0][0]
    if raw is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return f"FALHA {case_id}: mês: esperava uma data AAAA-MM-DD, veio {raw!r}"
    return f"ok    {case_id}: mês {raw}"


def _run(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    command = [
        "databricks",
        "--profile",
        profile,
        "api",
        "post",
        "/api/2.0/sql/statements",
        "--json",
        json.dumps(body),
        "-o",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"consulta falhou: {result.stderr.strip()}")
    response = json.loads(result.stdout)
    if response.get("status", {}).get("state") != "SUCCEEDED":
        raise RuntimeError(f"consulta não terminou: {response.get('status')}")
    return list(response.get("result", {}).get("data_array", []))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    args = parser.parse_args(argv)

    catalog = CATALOGS[args.target]
    lines = []
    for case in load_cases():
        if "reference_sql" not in case:  # recusas não têm SQL de referência
            continue
        try:
            rows = _run(
                args.profile, args.warehouse_id, for_catalog(case["reference_sql"], catalog)
            )
            lines.append(check_value(case["id"], rows))
            if "reference_month_sql" in case:
                month_rows = _run(
                    args.profile,
                    args.warehouse_id,
                    for_catalog(case["reference_month_sql"], catalog),
                )
                lines.append(check_month(case["id"], month_rows))
        except RuntimeError as error:
            lines.append(f"FALHA {case['id']}: {error}")
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
