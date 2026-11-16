# eval

Golden set e scorers do agente. Governado pela [SPEC-008](../docs/specs/008-agent-evaluation/spec.md).

## `golden_set.yaml` (P9.1)

30 casos: 20 `metric`, 5 `comparison` e 5 `refusal`. Cada caso guarda a SQL de referência, não o número; a SQL sempre devolve 1 valor (`AS value`) e lê só `atlas.semantic`. O catálogo `atlas` vira `atlas_dev` no `dev` (`scripts/check_golden_set.py`). Mês de referência: outubro de 2026.

## `sync_golden_set.py` (P9.2)

Job `atlas_eval_sync` (`databricks bundle run atlas_eval_sync -t dev`): sincroniza o YAML com o dataset MLflow `<catalog>.eval.agent_golden_set`. Cada caso vira `inputs = {question}` e `expectations` (id, categoria, `reference_sql`, view esperada, tolerância, comportamento); nunca o número (com o catálogo do target: `atlas_dev` no `dev`). O dataset espelha o YAML: sem mudança, nada é gravado; se o dataset tem um registro que o YAML não tem mais (pergunta editada, caso removido), a tabela é recriada (perde o histórico de versões) e o job confere ids e conteúdo no fim. A `reference_sql` só pode ler `atlas.semantic`. Confira com `scripts/check_agent_golden_set.py`.


## `scorers.py` (P9.3)

Os 4 scorers de código da SPEC-008 §4: `numeric_match`, `cites_metric_view`, `read_only_tools` e `no_tool_on_refusal`. A lógica fica em funções puras `check_*` (testadas com traces fake em `tests/test_eval_scorers.py`, cobertura 100%); `build_scorers()` as envolve com `@scorer` do MLflow e importa o `mlflow` só ali. O `numeric_match` lê `expectations["expected_value"]`: quem roda a avaliação (P10.6) executa a `reference_sql` antes e injeta o número. Fora da categoria de um scorer, o valor é `"n/a"`. A lista de tools do `read_only_tools` é a da SPEC-005 §3 (`ALLOWED_TOOLS`, com teste de consistência contra a spec).
