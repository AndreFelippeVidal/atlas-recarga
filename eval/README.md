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

## `gate.py` e `agent-eval.yml` (P10.7)

Gate de PR do agente ([SPEC-008](../docs/specs/008-agent-evaluation/spec.md) §5). O workflow `.github/workflows/agent-eval.yml` é chamado pelo job `agent-eval` do `ci.yml` (que o `ci-ok` aguarda, então o gate bloqueia o merge) só quando `apps/agent/**`, `eval/**` ou `semantic/**` mudam (PR só de `docs/` não dispara), executa `run_offline_eval.py --repeats 1 --json-out` no `dev` e passa o resumo para `eval/gate.py`, que falha o job se:

- a acurácia (pior rodada) é < 90%, **ou**
- qualquer caso `refusal` falha, **ou**
- qualquer caso falha em `read_only_tools` (tool fora da lista fechada), **ou**
- a acurácia cai mais de 5 pontos contra a última execução da `main`.

O resultado vira um comentário no PR (atualizado a cada push) com a acurácia, os casos que falharam e o link do run do MLflow. A linha de base é o run mais recente com a tag `branch=main` em `/Shared/atlas/agent-eval`: o próprio workflow a registra no push na `main`. Sem execução anterior, a regra da queda é pulada.

Configuração (uma vez, no Environment `ci-databricks` do [ADR-0015](../docs/adr/0015-ci-databricks-auth.md)): os secrets `DATABRICKS_HOST` e `DATABRICKS_TOKEN` já existem; faltam as **variáveis** `ATLAS_WAREHOUSE_ID` e `ATLAS_GENIE_SPACE_ID`. PRs de fork e do Dependabot não recebem secrets: o job é pulado.

Custo: ~31 chamadas ao agente por execução, com o limite de 30 req/min do gateway (ADR-0021): cerca de 10 a 20 minutos.

Teste local da decisão: `uv run pytest tests/test_eval_gate.py`.

Limites conhecidos: o `apps/agent/uv.lock` é ignorado pelo git, então o job resolve as dependências do agente sem lock (versões podem variar entre execuções); a linha de base é a última execução da `main` (que o push na `main` grava mesmo se o gate falhar), então uma regressão gradual de até 5 pontos por merge passa; o comentário é publicado por um job separado, sem secrets do Databricks (só ele tem `pull-requests: write`).

## `monitoring.py`, `run_agent_monitoring.py` e `start_monitoring.py` (P10.8)

Monitoramento do agente em produção ([SPEC-008](../docs/specs/008-agent-evaluation/spec.md) §6). O job `atlas_agent_monitoring` (07:00, depois do `atlas_daily`) lê os traces de `/Shared/atlas/agent-traces` e grava, de forma idempotente:

| Objeto | O que é |
|---|---|
| `observability.agent_quality_traces` | um trace por linha (latência, status) |
| `observability.agent_quality_scores` | um trace e um scorer por linha |
| `observability.agent_quality_daily` (view) | % de pass por scorer por dia e média de 7 dias |
| `observability.agent_traffic_daily` (view) | volume e latência p95 por dia |
| `observability.agent_quality_alert` (view) | alvo do SQL alert (`cites_metric_view` e `read_only_tools` abaixo de 90% na média de 7 dias) |
| `eval.review_queue` | fila de revisão: todo scorer que reprovou; o job só insere, quem revisa muda o `status` |

- **Scorers de código** (100% dos traces): `read_only_tools` e `cites_metric_view`. Sem `expectations` em produção, `cites_metric_view` é `n/a` se o trace não chamou tool de dados, e senão exige o bloco `Fonte:` e uma consulta a `mv_recharges` ou `mv_commission` (SPEC-008 §4).
- **LLM judges** (~20%, por hash do `trace_id`): `refusal_quality` (só sem tool de dados), `safety`, `relevance`, com o modelo de `--judge-model` (padrão `databricks:/databricks-gpt-oss-120b`, **fora** do `agent_llm`, para não gastar o rate limit do agente). Se o production monitoring (Beta) já anexou a assessment, o job a reaproveita; senão roda o judge (plano B).
- **Painel** "Atlas — Qualidade do agente" (`semantic/dashboards/agent_quality.lvdash.json`) e o **alerta** por e-mail para quem faz o deploy estão no `databricks.yml`.

Passos do mantenedor, no `dev`:

```bash
databricks bundle deploy -t dev --profile <perfil>
# Beta primeiro: liga os 3 judges (amostra de 20%). Sem --start só mostra o que faria.
# --experiment-id: o id de atlas_agent_traces em `databricks bundle summary -t dev` (no dev o nome
# ganha o prefixo do bundle, então o caminho /Shared/atlas/agent-traces não serve).
uv run --project apps/agent python eval/start_monitoring.py --profile <perfil> \
    --experiment-id <id> --start
# Gere tráfego no agente e rode o job; depois confira.
databricks bundle run atlas_agent_monitoring -t dev --profile <perfil>
uv run python scripts/check_agent_monitoring.py --profile <perfil> --warehouse-id <id> --catalog atlas_dev
```

Se o Beta não funcionar (o S0.3 não validou o judge em amostra), não ligue nada: o job faz o mesmo sozinho. Teste local da lógica: `uv run pytest tests/test_eval_monitoring.py tests/test_check_agent_monitoring.py tests/test_agent_quality_bundle.py`.
