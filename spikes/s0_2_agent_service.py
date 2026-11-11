# Databricks notebook source
# MAGIC %md
# MAGIC # S0.2 — Agent service (Beta) (DESCARTÁVEL)
# MAGIC
# MAGIC Spike da [SPEC-000](../docs/specs/000-platform-spike/spec.md) §2, item S0.2.
# MAGIC Não é código de produção e não deve ser reaproveitado.
# MAGIC
# MAGIC **Passou se:** o agente "hello" (App em `spikes/s0_2_hello_agent/`) aparece no
# MAGIC Unity Gateway (aba Agents) com uso registrado.
# MAGIC Plano B: governar só o LLM; o agente fica como App direto.
# MAGIC
# MAGIC ## Roteiro (mantenedor)
# MAGIC 1. Criar o App `agent-atlas-hello` (o prefixo `agent-` lista o App em Agents) a partir
# MAGIC    de `spikes/s0_2_hello_agent/` (Compute > Apps > Create app > Custom) e fazer o deploy.
# MAGIC 2. Se a chamada der `PERMISSION_DENIED`, dar ao service principal do App acesso ao model
# MAGIC    service `system.ai.gpt-oss-120b` (lição da S0.1: permissão de serving endpoint não vale).
# MAGIC 3. Em *Unity Gateway > Agents*, tentar registrar o App como agent service. Anotar os passos
# MAGIC    e o que a UI oferece. Não há comando de CLI para agent service (a v1.24.0 de
# MAGIC    `databricks ai-gateway` só tem model, model-provider, MCP e skills).
# MAGIC 4. Chamar do terminal com um token OAuth de usuário (obtido pelo CLI do Databricks; não
# MAGIC    cole o token em lugar nenhum): `POST $URL/invocations` com o cabeçalho
# MAGIC    `Authorization: Bearer <token>` e o corpo `{"message":"Responda apenas: ok"}`.
# MAGIC    Esperado: `{"output":"ok"}`.
# MAGIC 5. Rodar as células abaixo e anotar saída e erros exatos em `docs/spikes/S0-results.md`.

# COMMAND ----------

# MAGIC %pip install -U databricks-sdk requests
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

import requests
from databricks.sdk import WorkspaceClient

APP_NAME = "agent-atlas-hello"  # o prefixo agent- faz o App entrar na lista Agents
w = WorkspaceClient()
app = w.apps.get(APP_NAME)
print("estado:", app.app_status.state if app.app_status else None, "| url:", app.url)

# COMMAND ----------

# O token do notebook NÃO é aceito pelo Apps (devolve a tela de Sign In com status 200).
# Chame o agente do terminal com OAuth de usuário (ver roteiro) e registre a saída.
# Esta célula só detecta o caso da tela de login, para não confundir com sucesso.
token = w.config.authenticate()["Authorization"]
resp = requests.post(
    f"{app.url}/invocations",
    headers={"Authorization": token},
    json={"message": "Responda apenas: ok"},
    timeout=60,
)
is_login_page = "text/html" in resp.headers.get("content-type", "")
print(resp.status_code, "LOGIN PAGE (sem token OAuth)" if is_login_page else resp.text[:300])

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Uso do LLM chamado pelo agente (camada do modelo). Pode demorar minutos.
# MAGIC SELECT event_time, destination_name, status_code, input_tokens, output_tokens,
# MAGIC        requester_type, api_type
# MAGIC FROM system.ai_gateway.usage
# MAGIC WHERE event_time >= current_timestamp() - INTERVAL 2 HOURS
# MAGIC ORDER BY event_time DESC
# MAGIC LIMIT 20

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Há linha do próprio agente? Veja as colunas de destino e requester.
# MAGIC DESCRIBE TABLE system.ai_gateway.usage
