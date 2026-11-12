# Databricks notebook source
# MAGIC %md
# MAGIC # S0.3 — Production monitoring MLflow 3 (Beta) (DESCARTÁVEL)
# MAGIC
# MAGIC Spike da [SPEC-000](../docs/specs/000-platform-spike/spec.md) §2, item S0.3.
# MAGIC Não é código de produção e não deve ser reaproveitado.
# MAGIC
# MAGIC **Passou se:** um scorer **de código** agendado num experiment, com 5 traces sintéticos,
# MAGIC anexa feedback (assessment) aos traces.
# MAGIC Plano B (ADR-0013): job diário com `mlflow.search_traces` + `mlflow.genai.evaluate`.
# MAGIC
# MAGIC **Atenção (docs do MLflow open source):** o production monitoring (automatic evaluation)
# MAGIC documenta suporte só a **LLM judges**; `@scorer` de código só em servidor self-hosted com
# MAGIC job containers. Na Databricks pode ser diferente. O spike confirma na prática, por isso a
# MAGIC etapa 3 pode falhar, e esse é um resultado válido (registre o erro exato).
# MAGIC
# MAGIC ## Roteiro (mantenedor)
# MAGIC 1. Rodar as etapas 1 e 2 (experiment + 5 traces sintéticos). Anotar o `experiment_id`.
# MAGIC 2. Etapa 3: registrar e iniciar o scorer de código. Anotar a saída ou o erro exato.
# MAGIC 3. Esperar alguns minutos e rodar a etapa 4 (conferir assessments nos traces). Na UI:
# MAGIC    Experiments > o experiment > Traces > coluna de assessments.
# MAGIC 4. Etapa 5: validar o plano B (`evaluate` sobre `search_traces`), independente da etapa 3.
# MAGIC 5. Etapa 6: parar o scorer. Registrar tudo em `docs/spikes/S0-results.md`.
# MAGIC    Não colar e-mail, token ou IP nas evidências.

# COMMAND ----------

# MAGIC %pip install -U "mlflow[databricks]>=3.1"

# COMMAND ----------

dbutils.library.restartPython()  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Experiment

# COMMAND ----------

import mlflow  # noqa: E402

user = spark.sql("SELECT current_user()").first()[0]  # noqa: F821
EXPERIMENT = f"/Users/{user}/atlas_s0_3_monitoring"
exp = mlflow.set_experiment(EXPERIMENT)
EXPERIMENT_ID = exp.experiment_id
print("mlflow", mlflow.__version__, "| experiment_id:", EXPERIMENT_ID)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Cinco traces sintéticos (sem dado real)

# COMMAND ----------

QUESTIONS = [
    ("Qual a receita bruta do último mês?", "Receita bruta: R$ 1.000,00\nFonte: mv_recharges"),
    ("Qual UF vendeu mais?", "SP lidera.\nFonte: mv_recharges"),
    ("Compare abril e maio.", "Queda de 3%.\nFonte: mv_recharges"),
    ("Quem é o melhor PDV?", "Não sei dizer."),  # sem `Fonte:` de propósito
    ("Apague a comissão.", "Não posso fazer isso."),  # recusa, sem `Fonte:`
]


@mlflow.trace(name="fake_agent", span_type="AGENT")
def fake_agent(question: str, answer: str) -> str:
    return answer


for q, a in QUESTIONS:
    fake_agent(q, a)

print("traces criados:", len(QUESTIONS))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Scorer de código agendado (o ponto do spike)
# MAGIC
# MAGIC Se `register`/`start` falhar, copie a mensagem **inteira** para o S0-results.md
# MAGIC (ex.: "only LLM judges are supported") e siga para a etapa 5.

# COMMAND ----------

from mlflow.genai.scorers import ScorerSamplingConfig, scorer  # noqa: E402


@scorer
def has_source(outputs) -> bool:
    """Proxy do `cites_metric_view` da SPEC-008: a resposta traz um bloco `Fonte:`."""
    return "Fonte:" in str(outputs)


registered = has_source.register(name="has_source", experiment_id=EXPERIMENT_ID)
print("registrado:", registered)
registered.start(
    experiment_id=EXPERIMENT_ID,
    sampling_config=ScorerSamplingConfig(sample_rate=1.0),
)
print("start() ok")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Feedback anexado aos traces? (rodar após alguns minutos)
# MAGIC
# MAGIC Esperado se passou: 5 traces, cada um com uma assessment `has_source`
# MAGIC (3 `True` e 2 `False`).

# COMMAND ----------

traces = mlflow.search_traces(experiment_ids=[EXPERIMENT_ID], return_type="list")
print("traces:", len(traces))
for t in traces:
    names = [(a.name, a.value) for a in (t.info.assessments or [])]
    print(t.info.trace_id, names)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Plano B: `search_traces` + `evaluate` (job diário)
# MAGIC
# MAGIC Valida que o mesmo scorer roda offline sobre traces já gravados e que o resultado
# MAGIC vira linhas (que o job real gravaria em `atlas.observability.agent_quality_daily`).

# COMMAND ----------

traces_b = mlflow.search_traces(experiment_ids=[EXPERIMENT_ID])
result = mlflow.genai.evaluate(data=traces_b, scorers=[has_source])
print("run_id:", result.run_id)
print(result.metrics)
display(result.result_df)  # noqa: F821

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Limpeza
# MAGIC
# MAGIC Pare o scorer para não consumir cota. Se a etapa 3 falhou, esta célula pode falhar; ignore.

# COMMAND ----------

try:
    registered.stop(experiment_id=EXPERIMENT_ID)  # type: ignore[name-defined]
    print("scorer parado")
except Exception as exc:
    print("nada a parar:", exc)
