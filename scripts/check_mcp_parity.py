"""Paridade do `atlas-mcp` com o golden set (SPEC-006 §7, critério 6; task P11.4).

Reformula cada caso `metric` do `eval/golden_set.yaml` como uma chamada de `query_metric` e compara
o número com o da `reference_sql` (SPEC-008). O App só existe no workspace, então o **mantenedor**
roda isto depois do deploy:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_mcp -t dev --profile andrevidal
    uv run python scripts/check_mcp_parity.py --profile andrevidal \\
        --warehouse-id <id> --catalog atlas_dev

Cobre os 20 casos `metric`. Os casos `comparison` usam fórmulas próprias (variação %, diferença em
pontos) e ficam fora; `compare_months` é conferido por `check_mcp_tools.py`. Só lê. São ~20
chamadas: fica abaixo do limite de 30 por minuto do MCP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

APP_NAME = "atlas-mcp"
GOLDEN_SET = Path(__file__).resolve().parents[1] / "eval" / "golden_set.yaml"
CATALOGS = {"atlas": "atlas", "atlas_dev": "atlas_dev"}
REL_TOLERANCE = Decimal("0.000000001")  # só o ruído de ponto flutuante das taxas

_SELECT = re.compile(
    r"SELECT\s+MEASURE\((?P<measure>[a-z_]+)\)\s*(?:\*\s*(?P<scale>\d+)\s*)?AS\s+value\s+"
    r"FROM\s+atlas\.semantic\.(?P<view>[a-z_]+)\s+WHERE\s+(?P<where>.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_MONTH = re.compile(r"(?:recharge|reference)_month\s*=\s*DATE'(\d{4}-\d{2})-01'")
_FILTER = re.compile(r"(?P<key>[a-z_]+)\s*=\s*'(?P<value>[^']*)'")


def translate(reference_sql: str) -> dict[str, Any] | None:
    """Reformula a `reference_sql` de um caso `metric` como argumentos de `query_metric`.

    Devolve `None` se o SQL não tem a forma esperada (o relatório aponta o caso).
    """
    match = _SELECT.fullmatch(" ".join(reference_sql.split()))
    if not match:
        return None
    where = match["where"]
    month = _MONTH.search(where)
    if not month:
        return None
    rest = _MONTH.sub("", where)
    filters = {m["key"]: m["value"] for m in _FILTER.finditer(rest)}
    leftover = _FILTER.sub("", rest).replace("AND", "").strip()
    if leftover:
        return None
    return {
        "view": match["view"],
        "measures": [match["measure"]],
        "dimensions": [],
        "filters": filters,
        "month_from": month[1],
        "month_to": month[1],
        "scale": Decimal(match["scale"] or 1),
    }


def compare(case_id: str, mcp_value: Any, expected: Any) -> str:
    """Uma linha de relatório: `ok ...` ou `FALHA ...`. Mesma engine: espera-se igualdade."""
    try:
        got, want = Decimal(str(mcp_value)), Decimal(str(expected))
    except InvalidOperation:
        return f"FALHA {case_id}: valor não numérico (mcp={mcp_value!r}, sql={expected!r})"
    if got == want or (want != 0 and abs(got - want) / abs(want) <= REL_TOLERANCE):
        return f"ok    {case_id}: {got}"
    return f"FALHA {case_id}: mcp={got} sql={want}"


def _sql(profile: str, warehouse_id: str, statement: str) -> str | None:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    command = ["databricks", "--profile", profile, "api", "post", "/api/2.0/sql/statements"]
    command += ["--json", json.dumps(body), "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    response = json.loads(result.stdout)
    if response.get("status", {}).get("state") != "SUCCEEDED":
        raise RuntimeError(str(response.get("status")))
    data = response.get("result", {}).get("data_array", [])
    if len(data) != 1 or len(data[0]) != 1:
        raise RuntimeError("a reference_sql não devolveu 1 valor")
    value = data[0][0]
    return None if value is None else str(value)


def bearer_token(headers: Mapping[str, str]) -> str:
    scheme, _, token = headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise ValueError("o perfil não devolveu um cabeçalho Authorization Bearer")
    return token


async def _mcp_values(url: str, token: str, calls: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    out: dict[str, Any] = {}
    async with Client(url, auth=token) as client:
        for case_id, args in calls.items():
            payload = {k: v for k, v in args.items() if k != "scale"}
            try:
                data = (await client.call_tool("query_metric", payload)).data
                value = data["rows"][0][-1] if data["rows"] else None
                out[case_id] = None if value is None else Decimal(str(value)) * args["scale"]
            except ToolError as exc:
                out[case_id] = f"erro: {exc}"
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--catalog", choices=sorted(CATALOGS), required=True)
    args = parser.parse_args(argv)

    cases = [
        c
        for c in yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
        if c["category"] == "metric"
    ]
    lines: list[str] = []
    calls: dict[str, dict[str, Any]] = {}
    for case in cases:
        translated = translate(case["reference_sql"])
        if translated is None:
            lines.append(f"FALHA {case['id']}: reference_sql fora da forma esperada")
        else:
            calls[case["id"]] = translated

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)
    app = w.apps.get(APP_NAME)
    state = app.app_status.state.value if app.app_status and app.app_status.state else None
    if state != "RUNNING" or not app.url:
        print(f"FALHA: {APP_NAME} em {state!r} (rode `bundle run atlas_mcp`)")
        return 1
    values = asyncio.run(
        _mcp_values(f"{app.url.rstrip('/')}/mcp", bearer_token(w.config.authenticate()), calls)
    )
    for case in cases:
        case_id = case["id"]
        if case_id not in calls:
            continue
        got = values[case_id]
        if isinstance(got, str):
            lines.append(f"FALHA {case_id}: {got}")
            continue
        try:
            sql = case["reference_sql"].replace("atlas.semantic.", f"{args.catalog}.semantic.")
            lines.append(compare(case_id, got, _sql(args.profile, args.warehouse_id, sql)))
        except RuntimeError as error:
            lines.append(f"FALHA {case_id}: {error}")
    print("\n".join(lines))
    failed = any(line.startswith("FALHA") for line in lines)
    if not failed:
        print(f"OK: P11.4 critério 6 ({len(calls)} casos metric iguais ao SQL de referência)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
