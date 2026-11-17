"""Liga o experiment do agente às trace tables `<catalog>.observability.agent_*` (P10.5).

SPEC-005 §5.

Passo do **mantenedor**, uma vez por target, depois do `bundle deploy`: o MLflow cria as tabelas no
schema quando se define o trace location do experiment, e o service principal do App recebe as
permissões mínimas (USE CATALOG, USE SCHEMA em `observability`; SELECT e MODIFY só nas tabelas
`agent_*` recém-criadas, nunca no schema inteiro). Roda no ambiente do App (tem o mlflow):

    uv run --project apps/agent python scripts/setup_agent_trace_tables.py \\
        --profile andrevidal --catalog atlas_dev --warehouse-id <id> \\
        --experiment-id <id do experiment atlas_agent_traces> --app-sp <service_principal_client_id>

O id do experiment e o do service principal saem de `databricks bundle summary -t dev` e de
`databricks apps get agent-atlas`. Sem `--apply` só mostra o que faria.
Requer mlflow >= 3.11 (o App fixa 3.18). Não foi exercitado contra o workspace na preparação da
P10.5: se o `set_experiment` recusar o trace location, a mensagem do MLflow diz o que falta.
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
TABLE_PREFIX = "agent"
_IDENT = re.compile(r"^[A-Za-z0-9_]+$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_TABLE = re.compile(rf"^{TABLE_PREFIX}_[A-Za-z0-9_]+$")


def grant_statements(catalog: str, principal: str, objects: Sequence[tuple[str, str]]) -> list[str]:
    """GRANTs mínimos nos objetos `agent_*` (nunca no schema inteiro).

    `objects` traz `(nome, table_type)` da information_schema: tabela recebe SELECT e MODIFY; view
    (ex.: `agent_trace_metadata`) só SELECT, pois MODIFY não vale para view.
    """
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
    parser.add_argument(
        "--app-sp", required=True, help="service_principal_client_id do agent-atlas"
    )
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
    # Não é o payload do LLM (`agent_llm_payload`): o gateway escreve nele, não o App.
    objects = [
        (str(r[0]), str(r[1]))
        for r in rows
        if r[0] and _TABLE.fullmatch(str(r[0])) and not str(r[0]).endswith("_payload")
    ]
    if not objects:
        print("FALHA: nenhum objeto agent_* apareceu; confira o trace location no experiment.")
        return 1
    for statement in grant_statements(args.catalog, args.app_sp, objects):
        _sql(args.profile, args.warehouse_id, statement)
        print(f"ok   {statement}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
