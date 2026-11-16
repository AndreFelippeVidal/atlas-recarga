"""Sincroniza `eval/golden_set.yaml` com o dataset de avaliação do MLflow (SPEC-008 §3, task P9.2).

Roda como `spark_python_task` serverless no job `atlas_eval_sync` (databricks.yml), que recebe o
catálogo do target e o caminho do YAML sincronizado pelo bundle. O dataset vive em
`<catalog>.eval.agent_golden_set`; o schema `eval` já existe (setup do workspace). Nunca se edita o
dataset à mão: a fonte de verdade é o YAML.

* A `reference_sql` do YAML usa o catálogo `atlas`; o sync troca pelo catálogo do target
  (`atlas_dev` no `dev`), como `scripts/check_golden_set.py`: o scorer roda a SQL no catálogo certo.
* Cada caso vira um registro `{"inputs": {"question"}, "expectations": {...}}`.
* O registro guarda a **SQL de referência**, nunca o número: o valor esperado é recalculado a cada
  rodada sobre as metric views.
* O dataset espelha o YAML. `merge_records` casa pelas `inputs` e só soma; por isso, se o dataset
  tem um registro que o YAML não tem mais (pergunta editada, caso removido, campo removido), a
  tabela é recriada. Sem mudança, nada é gravado. Depois do sync o job confere ids e conteúdo.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
DATASET_SCHEMA = "eval"
DATASET_TABLE = "agent_golden_set"
# O dataset gerenciado exige um experiment; o mesmo do agente (SPEC-005 §3), criado se faltar.
EXPERIMENT_NAME = "/Shared/atlas/agent"
CATEGORIES = frozenset({"metric", "comparison", "refusal"})
# Campos do YAML (SPEC-008 §3) que viram expectations; `question` vai em inputs.
REQUIRED_FIELDS = {
    "sql": ("reference_sql", "expected_source_view", "tolerance_pct"),  # metric e comparison
    "refusal": ("expected_behavior", "forbidden_tools"),
}
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


_THREE_PART_NAME = re.compile(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b")
_SEMANTIC_PREFIX = re.compile(r"\batlas\.semantic\.")


def check_reads_only_semantic(case_id: str, sql: str) -> None:
    """Todo nome de 3 partes da SQL tem de ser `atlas.semantic.*` (só semantic é lido)."""
    names = _THREE_PART_NAME.findall(sql)
    if not names:
        raise ValueError(f"{case_id}: reference_sql sem tabela atlas.semantic.*")
    for catalog, schema, table in names:
        if (catalog, schema) != ("atlas", "semantic"):
            raise ValueError(f"{case_id}: reference_sql lê {catalog}.{schema}.{table}")


def for_catalog(sql: str, catalog: str) -> str:
    return _SEMANTIC_PREFIX.sub(f"{catalog}.semantic.", sql)


def to_records(cases: list[dict[str, Any]], catalog: str = "atlas") -> list[dict[str, Any]]:
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
        required = REQUIRED_FIELDS["refusal" if case["category"] == "refusal" else "sql"]
        missing = [k for k in required if case.get(k) in (None, "", [])]
        if missing:
            raise ValueError(f"{case_id}: campos ausentes {missing}")
        expectations = {k: case[k] for k in EXPECTATION_FIELDS if k in case}
        if "reference_sql" in expectations:
            check_reads_only_semantic(case_id, expectations["reference_sql"])
            expectations["reference_sql"] = for_catalog(expectations["reference_sql"], catalog)
        records.append({"inputs": {"question": question}, "expectations": expectations})
    return records


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value)


def fingerprints(rows: list[dict[str, Any]]) -> set[str]:
    """Uma impressão por registro (inputs + expectations conhecidas), ignorando campos extras."""
    prints = set()
    for row in rows:
        expectations = _as_dict(row["expectations"])
        kept = {k: expectations[k] for k in EXPECTATION_FIELDS if k in expectations}
        prints.add(json.dumps([_as_dict(row["inputs"]), kept], sort_keys=True, ensure_ascii=False))
    return prints


def has_stale_rows(existing: list[dict[str, Any]], desired: list[dict[str, Any]]) -> bool:
    """Há no dataset um registro que o YAML não tem (editado, removido)? Então é preciso recriar."""
    return bool(fingerprints(existing) - fingerprints(desired))


def verify_mirror(existing: list[dict[str, Any]], desired: list[dict[str, Any]]) -> None:
    """O dataset tem de ser igual ao YAML: mesmo número de linhas, mesmo conteúdo."""
    if len(existing) != len(desired) or fingerprints(existing) != fingerprints(desired):
        raise RuntimeError(
            f"dataset diverge do YAML: {len(existing)} linhas no dataset, {len(desired)} casos"
        )


def is_not_found(error: Exception) -> bool:
    """O erro significa "o dataset não existe"? Qualquer outro (permissão, rede) deve subir."""
    code = str(getattr(error, "error_code", ""))
    text = str(error).lower()
    return code in {"RESOURCE_DOES_NOT_EXIST", "NOT_FOUND", "TABLE_OR_VIEW_NOT_FOUND"} or any(
        marker in text for marker in ("does not exist", "not found", "not_found")
    )


def _rows(dataset: Any) -> list[dict[str, Any]]:
    return list(dataset.to_df()[["inputs", "expectations"]].to_dict("records"))


def main(argv: list[str]) -> None:
    """`argv`: catálogo e caminho do `golden_set.yaml`."""
    catalog, yaml_path = argv
    name = dataset_name(catalog)
    records = to_records(load_cases(Path(yaml_path)), catalog)

    import mlflow.genai.datasets  # só existe no workspace; import tardio mantém o módulo testável
    from databricks.connect import DatabricksSession
    from databricks.sdk import WorkspaceClient

    spark = DatabricksSession.builder.remote(serverless=True).getOrCreate()  # exigido pelo MLflow
    WorkspaceClient().workspace.mkdirs(str(Path(EXPERIMENT_NAME).parent))
    experiment = mlflow.set_experiment(EXPERIMENT_NAME)  # cria se não existir

    def create() -> Any:
        return mlflow.genai.datasets.create_dataset(
            uc_table_name=name, experiment_id=[experiment.experiment_id]
        )

    try:
        dataset = mlflow.genai.datasets.get_dataset(name=name)
    except Exception as error:  # o MLflow não tem exceção própria de "não achei"
        if not is_not_found(error):
            raise
        print(f"dataset {name} não encontrado; criando")
        dataset = create()
    if has_stale_rows(_rows(dataset), records):
        print(f"{name} tem registros que o YAML não tem mais; recriando")
        spark.sql(f"DROP TABLE IF EXISTS {name}")
        dataset = create()
    if fingerprints(_rows(dataset)) == fingerprints(records):
        print(f"{name} já é igual ao YAML; nada a gravar")
    else:
        dataset.merge_records(records)
    verify_mirror(_rows(mlflow.genai.datasets.get_dataset(name=name)), records)
    print(f"ok: {len(records)} casos sincronizados em {name}")


if __name__ == "__main__":
    # sem sys.exit: no serverless, `SystemExit` (até com 0) marca a task como falha
    main(sys.argv[1:])
