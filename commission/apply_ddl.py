"""Cria as tabelas de `<catalog>.commission` de `commission/ddl/*.sql` (SPEC-003 §3, task P8.2).

Roda como `spark_python_task` serverless no job `atlas_commission_deploy` (databricks.yml), que
recebe o catálogo do target e o diretório `commission/ddl` sincronizado pelo bundle. Idempotente:
`CREATE TABLE IF NOT EXISTS`. **Só cria tabelas**; não calcula nem aprova nada.

* Um arquivo por tabela, uma instrução por arquivo; o nome do arquivo é o nome da tabela.
* Só `${catalog}` é trocado, depois de validado; nada de SQL livre.
* `batch_events` e `locked_lines` nascem com `delta.appendOnly = true` (ADR-0010).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
CATALOG_PLACEHOLDER = "${catalog}"
SCHEMA = "commission"
TABLES = ("batches", "batch_lines", "batch_events", "locked_lines", "reconciliation")
APPEND_ONLY_TABLES = frozenset({"batch_events", "locked_lines"})


def check_identifier(value: str, what: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def load_definitions(directory: Path) -> list[tuple[str, str]]:
    """`(nome da tabela, texto do SQL)` na ordem de `TABLES`; falta ou sobra de arquivo é erro."""
    found = {check_identifier(p.stem, "table name"): p for p in directory.glob("*.sql")}
    if set(found) != set(TABLES):
        raise ValueError(f"esperado {sorted(TABLES)} em {directory}, achei {sorted(found)}")
    return [(name, found[name].read_text(encoding="utf-8")) for name in TABLES]


def build_ddl(catalog: str, name: str, sql_text: str) -> str:
    check_identifier(catalog, "catalog name")
    check_identifier(name, "table name")
    body = sql_text.replace(CATALOG_PLACEHOLDER, catalog).strip()
    if "${" in body:
        raise ValueError(f"{name}: placeholder desconhecido no SQL")
    if ";" in re.sub(r"'[^']*'", "", body):  # ';' dentro de um COMMENT '...' é texto
        raise ValueError(f"{name}: uma instrução por arquivo, sem ';'")
    return body


def main(catalog: str, directory: str) -> None:
    from pyspark.sql import SparkSession  # só existe no workspace

    check_identifier(catalog, "catalog name")
    spark: Any = SparkSession.builder.getOrCreate()
    for name, sql_text in load_definitions(Path(directory)):
        spark.sql(build_ddl(catalog, name, sql_text))
        print(f"aplicada: {catalog}.{SCHEMA}.{name}")


if __name__ == "__main__":
    # sem sys.exit: no serverless, `SystemExit` (até com 0) marca a task como falha
    main(sys.argv[1], sys.argv[2])
