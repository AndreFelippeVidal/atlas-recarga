# eval

Golden set e scorers do agente. Governado pela [SPEC-008](../docs/specs/008-agent-evaluation/spec.md).

## `golden_set.yaml` (P9.1)

30 casos: 20 `metric`, 5 `comparison` e 5 `refusal`. Cada caso guarda a SQL de referência, não o número; a SQL sempre devolve 1 valor (`AS value`) e lê só `atlas.semantic`. O catálogo `atlas` vira `atlas_dev` no `dev` (`scripts/check_golden_set.py`). Mês de referência: outubro de 2026.

## `sync_golden_set.py` (P9.2)

Job `atlas_eval_sync` (`databricks bundle run atlas_eval_sync -t dev`): sincroniza o YAML com o dataset MLflow `<catalog>.eval.agent_golden_set`. Cada caso vira `inputs = {question}` e `expectations` (id, categoria, `reference_sql`, view esperada, tolerância, comportamento); nunca o número (com o catálogo do target: `atlas_dev` no `dev`). Idempotente (`merge_records` casa pelas `inputs`); um caso removido do YAML não sai do dataset. Confira com `scripts/check_agent_golden_set.py`.

