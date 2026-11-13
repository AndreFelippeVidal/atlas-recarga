"""Confere o `delta.appendOnly` das tabelas de comissão (SPEC-003 §8, task P8.2).

Critério da P8.2: um UPDATE é rejeitado. As tabelas só existem no workspace, então o
**mantenedor** roda este script depois do deploy e do job `atlas_commission_deploy`:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_commission_deploy -t dev --profile andrevidal
    uv run python scripts/check_commission_append_only.py --target dev --profile andrevidal \\
        --warehouse-id <id>

1. Lê `SHOW TBLPROPERTIES` de `batch_events` e `locked_lines`: `delta.appendOnly = true`.
2. Confirma que `batches`, `batch_lines` e `reconciliation` **não** são append-only.
3. Numa tabela de sonda (`commission._probe_append_only`, descartada no fim), com a mesma
   propriedade, confirma que `UPDATE` e `DELETE` são rejeitados. Não toca nas linhas reais:
   uma linha de teste em `batch_events` ficaria para sempre na trilha de auditoria.

Sai com 0 se tudo confere e com 1 se algo falha.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
APPEND_ONLY = ("batch_events", "locked_lines")
MUTABLE = ("batches", "batch_lines", "reconciliation")
PROBE = "_probe_append_only"
REJECTION_MARKERS = ("DELTA_CANNOT_MODIFY_APPEND_ONLY", "only allow appends")


def properties_query(catalog: str, table: str) -> str:
    return f"SHOW TBLPROPERTIES {catalog}.commission.{table}"


def probe_statements(catalog: str) -> dict[str, str]:
    name = f"{catalog}.commission.{PROBE}"
    return {
        "create": f"CREATE OR REPLACE TABLE {name} (id INT, v STRING) USING DELTA "
        "TBLPROPERTIES ('delta.appendOnly' = 'true')",
        "insert": f"INSERT INTO {name} VALUES (1, 'a')",  # noqa: S608
        "update": f"UPDATE {name} SET v = 'b' WHERE id = 1",  # noqa: S608
        "delete": f"DELETE FROM {name} WHERE id = 1",  # noqa: S608
        "drop": f"DROP TABLE IF EXISTS {name}",
    }


def is_append_only(rows: Sequence[Sequence[str | None]]) -> bool:
    return any(key == "delta.appendOnly" and value == "true" for key, value, *_ in rows)


def is_rejection(error: str) -> bool:
    return any(marker in error for marker in REJECTION_MARKERS)


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
        raise RuntimeError(f"{result.stderr.strip()} {result.stdout.strip()}")
    response = json.loads(result.stdout)
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(json.dumps(status))
    return list(response.get("result", {}).get("data_array", []))


def check(profile: str, warehouse_id: str, catalog: str) -> list[str]:
    """Uma linha `ok`/`FALHA` por verificação; erro de infraestrutura vira `FALHA`, não traceback."""

    def run(statement: str) -> list[list[str | None]]:
        return _run(profile, warehouse_id, statement)

    lines: list[str] = []
    try:
        for table in APPEND_ONLY:
            ok = is_append_only(run(properties_query(catalog, table)))
            lines.append(f"{'ok   ' if ok else 'FALHA'} {table}: delta.appendOnly = true")
        for table in MUTABLE:
            ok = not is_append_only(run(properties_query(catalog, table)))
            lines.append(f"{'ok   ' if ok else 'FALHA'} {table}: não é append-only")
    except RuntimeError as error:
        return [*lines, f"FALHA não consegui ler as propriedades (o deploy rodou?): {error}"]

    sql = probe_statements(catalog)
    try:
        run(sql["create"])
        run(sql["insert"])
        for op in ("update", "delete"):
            try:
                run(sql[op])
                lines.append(f"FALHA {op.upper()} na sonda foi aceito")
            except RuntimeError as error:
                ok = is_rejection(str(error))
                lines.append(
                    f"{'ok   ' if ok else 'FALHA'} {op.upper()} na sonda rejeitado"
                    + ("" if ok else f" por outro motivo: {error}")
                )
    except RuntimeError as error:
        lines.append(f"FALHA a sonda não rodou: {error}")
    finally:
        try:
            run(sql["drop"])
        except RuntimeError as error:
            lines.append(f"FALHA não consegui descartar {PROBE}; apague à mão: {error}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda as consultas")
    args = parser.parse_args(argv)

    lines = check(args.profile, args.warehouse_id, CATALOGS[args.target])
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
