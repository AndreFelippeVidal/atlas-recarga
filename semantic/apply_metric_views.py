"""Aplica as metric views de `semantic/*.yaml` em `<catalog>.semantic` (SPEC-004 §2, task P7.1).

Roda como `spark_python_task` serverless no job `atlas_semantic_deploy` (databricks.yml), que
recebe o catálogo do target e o diretório `semantic/` já sincronizado pelo bundle. Não é
carregado pelo pipeline. Idempotente: `CREATE OR REPLACE VIEW`.

* O YAML é a fonte de verdade e vai **literal** para `AS $$ ... $$`; só `${catalog}` é trocado
  (o ADR-0005 avisa que reindentar o YAML quebra a definição).
* O nome da view é o nome do arquivo (`mv_recharges.yaml` -> `semantic.mv_recharges`).
* Só entram o catálogo validado e nomes de arquivo validados; nada de SQL livre.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
CATALOG_PLACEHOLDER = "${catalog}"
SCHEMA = "semantic"


def check_identifier(value: str, what: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


def load_definitions(directory: Path) -> list[tuple[str, str]]:
    """`(nome da view, texto do YAML)` de cada `*.yaml`, em ordem alfabética."""
    definitions = [
        (check_identifier(path.stem, "view name"), path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.yaml"))
    ]
    if not definitions:
        raise FileNotFoundError(f"nenhum *.yaml em {directory}")
    return definitions


def build_ddl(catalog: str, name: str, yaml_text: str) -> str:
    """`CREATE OR REPLACE VIEW ... WITH METRICS` com o YAML sem reindentar."""
    check_identifier(catalog, "catalog name")
    check_identifier(name, "view name")
    if "$$" in yaml_text:
        raise ValueError(f"{name}: o YAML não pode conter '$$'")
    body = yaml_text.replace(CATALOG_PLACEHOLDER, catalog)
    if "${" in body:
        raise ValueError(f"{name}: placeholder desconhecido no YAML")
    return (
        f"CREATE OR REPLACE VIEW {catalog}.{SCHEMA}.{name}\n"
        f"WITH METRICS\nLANGUAGE YAML\nAS $$\n{body}\n$$"
    )


def main(catalog: str, directory: str) -> None:
    from pyspark.sql import SparkSession  # só existe no workspace

    check_identifier(catalog, "catalog name")
    spark: Any = SparkSession.builder.getOrCreate()
    for name, yaml_text in load_definitions(Path(directory)):
        spark.sql(build_ddl(catalog, name, yaml_text))
        print(f"aplicada: {catalog}.{SCHEMA}.{name}")


if __name__ == "__main__":
    # sem sys.exit: no serverless, `SystemExit` (até com 0) marca a task como falha
    main(sys.argv[1], sys.argv[2])
