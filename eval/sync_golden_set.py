"""Sincroniza `eval/golden_set.yaml` com o dataset de avaliação do MLflow (SPEC-008 §3, task P9.2).

Roda como `spark_python_task` serverless no job `atlas_eval_sync` (databricks.yml), que recebe o
catálogo do target e o caminho do YAML sincronizado pelo bundle. O dataset vive em
`<catalog>.eval.agent_golden_set`; o schema `eval` já existe (setup do workspace). Nunca se edita o
dataset à mão: a fonte de verdade é o YAML.

* Cada caso vira um registro `{"inputs": {"question"}, "expectations": {...}}`.
* O registro guarda a **SQL de referência**, nunca o número: o valor esperado é recalculado a cada
  rodada sobre as metric views.
* `merge_records` casa os registros pelas `inputs`: uma execução sem mudança não cria versão nova.
  Limite conhecido: um caso removido do YAML continua no dataset (remoção é decisão humana).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
DATASET_SCHEMA = "eval"
DATASET_TABLE = "agent_golden_set"
CATEGORIES = frozenset({"metric", "comparison", "refusal"})
# Campos do YAML (SPEC-008 §3) que viram expectations; `question` vai em inputs.
EXPECTATION_FIELDS = (
    "id",
    "category",
    "reference_sql",
    "expected_source_view",
    "tolerance_pct",
    "expected_behavior",
    "forbidden_tools",
)


def dataset_name(catalog: str) -> str:
    if not _IDENTIFIER.fullmatch(catalog):
        raise ValueError(f"invalid catalog: {catalog!r}")
    return f"{catalog}.{DATASET_SCHEMA}.{DATASET_TABLE}"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path}: esperava uma lista não vazia de casos")
    return list(cases)


def to_records(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Converte os casos do YAML em registros do dataset MLflow, sem calcular nenhum valor."""
    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("id", ""))
        if not case_id or case_id in seen:
            raise ValueError(f"id ausente ou duplicado: {case_id!r}")
        seen.add(case_id)
        if case.get("category") not in CATEGORIES:
            raise ValueError(f"{case_id}: category inválida ({case.get('category')!r})")
        question = case.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"{case_id}: question ausente")
        expectations = {k: case[k] for k in EXPECTATION_FIELDS if k in case}
        records.append({"inputs": {"question": question}, "expectations": expectations})
    return records


def main(argv: list[str]) -> int:
    """`argv`: catálogo e caminho do `golden_set.yaml`."""
    catalog, yaml_path = argv
    name = dataset_name(catalog)
    records = to_records(load_cases(Path(yaml_path)))

    import mlflow.genai.datasets  # só existe no workspace; import tardio mantém o módulo testável
    from databricks.connect import DatabricksSession

    DatabricksSession.builder.remote(serverless=True).getOrCreate()  # exigido pelo MLflow
    try:
        dataset = mlflow.genai.datasets.get_dataset(name=name)
    except Exception as error:  # o MLflow não tem exceção própria de "não achei"
        print(f"dataset {name} não encontrado ({type(error).__name__}); criando")
        dataset = mlflow.genai.datasets.create_dataset(uc_table_name=name)
    dataset.merge_records(records)
    print(f"ok: {len(records)} casos sincronizados em {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
