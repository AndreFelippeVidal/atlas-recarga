# eval

Golden set e scorers do agente. Governado pela [SPEC-008](../docs/specs/008-agent-evaluation/spec.md).

## `golden_set.yaml` (P9.1)

31 casos: 20 `metric`, 5 `comparison`, 5 `refusal` e 1 `no_period` (P10.6: pergunta sem mês, o agente assume o último mês com dados e diz isso). Cada caso guarda a SQL de referência, não o número; a SQL sempre devolve 1 valor (`AS value`) e lê só `atlas.semantic`. O `no_period` tem também a `reference_month_sql`, que devolve o último mês com dados (`AAAA-MM-DD`); as duas olham o mês mais recente da view, então nada fixa outubro. O catálogo `atlas` vira `atlas_dev` no `dev` (`scripts/check_golden_set.py`). Mês de referência: outubro de 2026.

## `sync_golden_set.py` (P9.2)

Job `atlas_eval_sync` (`databricks bundle run atlas_eval_sync -t dev`): sincroniza o YAML com o dataset MLflow `<catalog>.eval.agent_golden_set`. Cada caso vira `inputs = {question}` e `expectations` (id, categoria, `reference_sql`, view esperada, tolerância, comportamento); nunca o número (com o catálogo do target: `atlas_dev` no `dev`). O dataset espelha o YAML: sem mudança, nada é gravado; se o dataset tem um registro que o YAML não tem mais (pergunta editada, caso removido), a tabela é recriada (perde o histórico de versões) e o job confere ids e conteúdo no fim. A `reference_sql` só pode ler `atlas.semantic`. Confira com `scripts/check_agent_golden_set.py`.

## `scorers.py` (P9.3)

Os 5 scorers de código da SPEC-008 §4: `numeric_match`, `cites_metric_view`, `read_only_tools`, `no_tool_on_refusal` e `declares_assumed_month` (P10.6: o `no_period` declara, nos primeiros 250 caracteres, o último mês com dados e só ele, o mês vem de uma tool e o número bate com a `reference_sql`). A lógica fica em funções puras `check_*` (testadas com traces fake em `tests/test_eval_scorers.py`, cobertura 100%); `build_scorers()` as envolve com `@scorer` do MLflow e importa o `mlflow` só ali. O `numeric_match` lê `expectations["expected_value"]`: quem roda a avaliação (`run_offline_eval.py`) executa a `reference_sql` antes e injeta o número (e o mês, em `expected_month`). Fora da categoria de um scorer, o valor é `"n/a"`. A lista de tools do `read_only_tools` é a da SPEC-005 §3 (`ALLOWED_TOOLS`, com teste de consistência contra a spec).

Convenções e limites (a confirmar na P10.2/P10.6, quando houver trace real):
- **Número principal:** o primeiro valor com `R$` ou `%`; senão o primeiro número que não seja ano nem ordinal. Escalas por extenso ("1,2 milhão") não são lidas.
- **`cites_metric_view`:** a view precisa aparecer, como identificador inteiro, nos inputs ou outputs de uma tool de dados (o retorno de `fn_list_metrics` não conta). Para o `ask_genie` isso é a SQL gerada. As UC functions ainda não dizem a view no retorno; o contrato de span delas (e o do Genie via App) é presumido e será fixado na P10.1/P10.2.
- **Nomes de tools:** `fn_x` ou `atlas*.semantic.fn_x`; outro prefixo reprova. Um trace sem spans TOOL passa em `read_only_tools` e `no_tool_on_refusal`, com aviso no rationale.

## `run_offline_eval.py` (P10.6)

Avaliação offline: roda o agente real em cada caso com `mlflow.genai.evaluate` e os 5 scorers, e imprime a acurácia por categoria, os casos que falharam (com o rationale) e o link do run do MLflow. Roda do ambiente de `apps/agent`, com o seu perfil e o gateway do `dev`:

```bash
uv run --project apps/agent python eval/run_offline_eval.py \
    --profile <perfil> --catalog atlas_dev --warehouse-id <id> --genie-space-id <id>
```

- Os valores esperados são recalculados a cada rodada nas metric views; nada numérico fica no repositório.
- `--repeats` (padrão 3): a resposta de um LLM varia, então são várias rodadas, cada uma um run em `/Shared/atlas/agent-eval`. Sai com 0 só se **todas** ficarem em ≥ 90% e sem falha em `refusal`. `--only GS-031` roda um caso, para depurar.
- A acurácia conta só os scorers de código. Os LLM judges (`refusal_quality`, `correctness`) não estão construídos; a qualidade do texto da recusa é lida por uma pessoa.
- Poucas threads (`MLFLOW_GENAI_EVAL_MAX_WORKERS=2`) e nova tentativa no 429: o gateway aceita 30 req/min (ADR-0021).
