# Databricks notebook source
# MAGIC %md
# MAGIC # S0.1 — Unity Gateway + model service (DESCARTÁVEL)
# MAGIC
# MAGIC Spike da [SPEC-000](../docs/specs/000-platform-spike/spec.md) §2, item S0.1.
# MAGIC Não é código de produção e não deve ser reaproveitado.
# MAGIC
# MAGIC **Passou se:** resposta 200 **e** uma linha em `system.ai_gateway.usage`.
# MAGIC
# MAGIC **Atenção:** a aba *Models* do workspace (2026-11-11) **não lista nenhum modelo Claude**
# MAGIC em `system.ai`. Este notebook valida o *mecanismo* do gateway com um modelo disponível
# MAGIC (`MODEL` abaixo) e, em separado, tenta o Claude para registrar o resultado.

# COMMAND ----------

# MAGIC %pip install -U databricks-langchain mlflow
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

from databricks_langchain import ChatDatabricks

# Use o nome de TRÊS PARTES do model service (catalog.schema.nome). O nome curto cai
# no endpoint legado e dá 403 "no longer available".
# Candidatos vistos no workspace: gpt-oss-120b, llama-4-maverick, gemma-3-12b.
# Candidato Claude (esperado falhar; registrar o erro exato): claude-sonnet-4-5
MODEL = "system.ai.gpt-oss-120b"
CLAUDE_CANDIDATE = "system.ai.claude-sonnet-4-5"

# COMMAND ----------


def ask(model: str) -> str:
    llm = ChatDatabricks(model=model, use_ai_gateway=True, max_tokens=32)
    return str(llm.invoke("Responda apenas: ok").content)


print("modelo disponível:", MODEL, "->", ask(MODEL))

# COMMAND ----------

# Tentativa Claude: o objetivo é registrar o erro (ou o sucesso), não esconder a falha.
try:
    print("claude ->", ask(CLAUDE_CANDIDATE))
except Exception as exc:
    print("claude FALHOU:", type(exc).__name__, exc)

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Evidência do "passou se": a chamada acima deve aparecer aqui (pode demorar).
# MAGIC SELECT event_time, destination_name, status_code, input_tokens, output_tokens,
# MAGIC        requester_type, api_type
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE event_time >= current_timestamp() - INTERVAL 2 HOURS
# MAGIC ORDER BY event_time DESC
# MAGIC LIMIT 20
