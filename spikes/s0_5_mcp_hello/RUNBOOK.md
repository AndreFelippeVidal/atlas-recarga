# S0.5 — Runbook (descartável)

Template oficial `databricks/app-templates/mcp-server-hello-world` (FastMCP), com uma tool a mais: `whoami_query`, que roda `SELECT current_user()` com o token do usuário (OBO). Profile: `andrevidal`. Rode a partir de `spikes/s0_5_mcp_hello/`.

## 1. Criar e implantar o App

```bash
databricks apps create atlas-s0-5-mcp --profile andrevidal \
  --description "S0.5 spike (descartável)"
```

No workspace, em **Compute → Apps → atlas-s0-5-mcp → Edit**:
- **Resources:** adicione `SQL warehouse` (Serverless Starter Warehouse) com a chave `sql-warehouse`, permissão *Can use*.
- **User authorization (OBO):** habilite com o escopo `sql`.

```bash
# IMPORTANTE: o sync tem de partir da pasta do spike, senão sobe o repo inteiro
# e o App não acha o app.yaml (erro "No command to run").
cd spikes/s0_5_mcp_hello
databricks sync . /Workspace/Users/<seu-email>/atlas-s0-5-mcp --profile andrevidal
databricks workspace list /Workspace/Users/<seu-email>/atlas-s0-5-mcp --profile andrevidal  # deve listar app.yaml e server/
databricks apps deploy atlas-s0-5-mcp --profile andrevidal \
  --source-code-path /Workspace/Users/<seu-email>/atlas-s0-5-mcp
databricks apps get atlas-s0-5-mcp --profile andrevidal   # anote a url
```

Se você já sincronizou a partir da raiz do repo, apague a pasta errada antes (o `sync` não remove o que ficou de fora):

```bash
databricks workspace delete /Workspace/Users/<seu-email>/atlas-s0-5-mcp --recursive --profile andrevidal
```

## 2. Teste do cliente externo

Opção A (spec): token OAuth do usuário + `claude mcp add`:

```bash
databricks auth token --profile andrevidal   # NÃO cole a saída aqui
claude mcp add --transport http atlas-s0-5 https://<app-url>/mcp \
  --header "Authorization: Bearer <token>"
```

Em uma sessão do Claude Code: peça "chame a tool health do atlas-s0-5" e depois "chame whoami_query".

Opção B (já vem no template): `./scripts/dev/query_remote.sh` faz o fluxo OAuth e chama as tools.

Se a plataforma recusar o cliente externo (302/401 para a página de login), é o caso do plano B: `mcp-remote` com token do `databricks auth` (ver SPEC-000 §2).

## 3. Evidência de OBO

```sql
SELECT executed_by, statement_text, start_time
FROM system.query.history
WHERE statement_text LIKE '%atlas-s0.5%'
ORDER BY start_time DESC LIMIT 5;
```

Passou se `executed_by` = seu usuário (e não o service principal do App).

## 4. Limpeza (libera o slot)

```bash
databricks apps delete atlas-s0-5-mcp --profile andrevidal
claude mcp remove atlas-s0-5
```
