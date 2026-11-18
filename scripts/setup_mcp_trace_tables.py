"""Liga o experiment do MCP às trace tables `<catalog>.observability.mcp_*` (P11.4).

SPEC-006 §6. Mesmo mecanismo do agente (`setup_agent_trace_tables.py`, SPEC-005 §5): o experiment
`atlas_mcp_traces` e o `CAN_EDIT` do App ficam no bundle; o **trace location** no UC e os GRANTs
mínimos não cabem no bundle (o MLflow cria as tabelas quando se define o location), então este é um
passo do **mantenedor**, uma vez por target, depois do `bundle deploy`:

    uv run --project apps/mcp python scripts/setup_mcp_trace_tables.py \\
        --profile andrevidal --catalog atlas_dev --warehouse-id <id> \\
        --experiment-id <id do atlas_mcp_traces> --app-sp <client_id do atlas-mcp> --apply

O id do experiment sai de `databricks bundle summary -t dev` e o do service principal de
`databricks apps get atlas-mcp`. Depois cria a view `observability.mcp_usage_daily`, lida pela
página "Uso do MCP" (chamadas, erros por código e p95 por tool e por dia), sobre os atributos
gravados nos spans. Se as colunas da tabela de spans forem outras, o script para sem criar a view e
mostra as colunas encontradas. Sem `--apply` só mostra o que faria. Não foi exercitado contra o
workspace na preparação da P11.4.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from typing import Any

SCHEMA = "observability"
TABLE_PREFIX = "mcp"
SPANS_TABLE = f"{TABLE_PREFIX}_otel_spans"
USAGE_VIEW = f"{TABLE_PREFIX}_usage_daily"
SPAN_COLUMNS = {"parent_span_id", "start_time_unix_nano", "end_time_unix_nano", "attributes"}
_IDENT = re.compile(r"^[A-Za-z0-9_]+$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_TABLE = re.compile(rf"^{TABLE_PREFIX}_[A-Za-z0-9_]+$")


def grant_statements(catalog: str, principal: str, objects: Sequence[tuple[str, str]]) -> list[str]:
    """GRANTs mínimos nos objetos `mcp_*` (nunca no schema inteiro): tabela SELECT e MODIFY, view
    só SELECT."""
    for value, pattern in ((catalog, _IDENT), (principal, _PRINCIPAL)):
        if not pattern.fullmatch(value):
            raise ValueError(f"valor inválido: {value!r}")
    bad = [name for name, _ in objects if not _TABLE.fullmatch(name)]
    if bad:
        raise ValueError(f"objetos fora do prefixo {TABLE_PREFIX}_: {bad}")
    statements = [
        f"GRANT USE CATALOG ON CATALOG {catalog} TO `{principal}`",
        f"GRANT USE SCHEMA ON SCHEMA {catalog}.{SCHEMA} TO `{principal}`",
    ]
    for name, table_type in objects:
        writable = table_type in ("MANAGED", "EXTERNAL")
        privileges = "SELECT, MODIFY" if writable else "SELECT"
        statements.append(f"GRANT {privileges} ON {catalog}.{SCHEMA}.{name} TO `{principal}`")
    return statements


def usage_view_sql(catalog: str) -> str:
    """View da página "Uso do MCP": um span raiz por chamada de tool, dia em America/Sao_Paulo."""
    if not _IDENT.fullmatch(catalog):
        raise ValueError(f"catálogo inválido: {catalog!r}")
    obs = f"{catalog}.{SCHEMA}"
    return f"""CREATE OR REPLACE VIEW {obs}.{USAGE_VIEW} (
  day COMMENT 'dia de negócio (America/Sao_Paulo)',
  tool COMMENT 'tool do MCP',
  error_code COMMENT 'código de erro do §4 da SPEC-006; vazio quando a chamada deu certo',
  calls COMMENT 'chamadas',
  duration_p95_ms COMMENT 'latência p95 em ms')
COMMENT 'Uso do atlas-mcp por tool, dia e código de erro (SPEC-006 §6). Só atributos dos spans.' AS
SELECT
  CAST(from_utc_timestamp(timestamp_nanos(start_time_unix_nano), 'America/Sao_Paulo') AS DATE)
    AS day,
  attributes['tool'] AS tool,
  COALESCE(attributes['error_code'], '') AS error_code,
  COUNT(*) AS calls,
  percentile_cont(0.95) WITHIN GROUP (
    ORDER BY CAST(attributes['duration_ms'] AS DOUBLE)) AS duration_p95_ms
FROM {obs}.{SPANS_TABLE}
WHERE parent_span_id IS NULL OR parent_span_id = ''
GROUP BY 1, 2, 3"""  # noqa: S608 - catálogo validado por regex; o resto é constante


def _sql(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    command = ["databricks", "--profile", profile, "api", "post", "/api/2.0/sql/statements"]
    command += ["--json", json.dumps(body), "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    response: dict[str, Any] = json.loads(result.stdout)
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(str(status.get("error", status)))
    return list(response.get("result", {}).get("data_array", []))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--app-sp", required=True, help="service_principal_client_id do atlas-mcp")
    parser.add_argument("--apply", action="store_true", help="executa (sem isto só mostra)")
    args = parser.parse_args(argv)
    if not _IDENT.fullmatch(args.catalog):
        parser.error("--catalog deve ser um identificador simples")
    print(
        f"trace location: {args.catalog}.{SCHEMA}, prefixo {TABLE_PREFIX!r}, "
        f"experiment {args.experiment_id}"
    )
    if not args.apply:
        print("dry-run: nada foi alterado (use --apply).")
        return 0

    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    os.environ.setdefault("MLFLOW_TRACKING_URI", "databricks")
    import mlflow
    from mlflow.entities.trace_location import UnityCatalog

    mlflow.set_experiment(
        experiment_id=args.experiment_id,
        trace_location=UnityCatalog(
            catalog_name=args.catalog, schema_name=SCHEMA, table_prefix=TABLE_PREFIX
        ),
    )
    # catalog validado por regex; o resto é constante
    rows = _sql(
        args.profile,
        args.warehouse_id,
        f"SELECT table_name, table_type FROM {args.catalog}.information_schema.tables "  # noqa: S608
        f"WHERE table_schema = '{SCHEMA}' AND table_name LIKE '{TABLE_PREFIX}\\_%' "
        "ORDER BY table_name",
    )
    objects = [(str(r[0]), str(r[1])) for r in rows if r[0] and _TABLE.fullmatch(str(r[0]))]
    if not objects:
        print("FALHA: nenhum objeto mcp_* apareceu; confira o trace location no experiment.")
        return 1
    for statement in grant_statements(args.catalog, args.app_sp, objects):
        _sql(args.profile, args.warehouse_id, statement)
        print(f"ok   {statement}")

    columns = {
        str(r[0])
        for r in _sql(
            args.profile,
            args.warehouse_id,
            f"SELECT column_name FROM {args.catalog}.information_schema.columns "  # noqa: S608
            f"WHERE table_schema = '{SCHEMA}' AND table_name = '{SPANS_TABLE}'",
        )
    }
    if not columns >= SPAN_COLUMNS:
        print(
            f"FALHA: {SPANS_TABLE} não tem as colunas esperadas {sorted(SPAN_COLUMNS)}; "
            f"achei {sorted(columns)}. Ajuste usage_view_sql e rode de novo."
        )
        return 1
    _sql(args.profile, args.warehouse_id, usage_view_sql(args.catalog))
    print(f"ok   view {args.catalog}.{SCHEMA}.{USAGE_VIEW}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
