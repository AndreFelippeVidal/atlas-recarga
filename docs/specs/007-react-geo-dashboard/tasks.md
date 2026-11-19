# Tasks — 007-react-geo-dashboard

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 12 — Dashboard React com mapa

### P12.1 🤖 `scripts/fetch_geo.py`: malhas do IBGE → TopoJSON simplificado em `apps/web/public/geo/`

- **Depende de:** P4.2
- **Pronto quando:** Tamanhos dentro do limite; teste de match de 100% com `dim_municipality`

### P12.2 🤖 Backend FastAPI: `/api/months`, `/api/kpis`, `/api/health` + cache

- **Depende de:** P7.1
- **Pronto quando:** Os KPIs batem com o AI/BI

### P12.3 🤖 `/api/map/region`, `/api/map/uf` e `/api/map/municipality` (com `mom_change`) + validação de `measure`

- **Depende de:** P12.2
- **Pronto quando:** 400 para medida inválida; a soma das regiões e a das UFs são iguais ao KPI

### P12.4 🤖 Frontend: esqueleto Vite + React + TS, layout, KPI cards

- **Depende de:** P0.5
- **Pronto quando:** Build no CI (`tsc`, `eslint`, `vitest`)

### P12.5 🤖 Mapa por região (UFs pintadas pela região) com `d3-geo`, escala de quantis, legenda, tooltip

- **Depende de:** P12.1, P12.3, P12.4
- **Pronto quando:** Visual conferido por você
- **Passos:**
  - Usar o skill dataviz para a paleta e a legenda

### P12.6 🤖 Drill-down: Brasil → região → UF → municípios, com zoom; breadcrumb e Esc

- **Depende de:** P12.5
- **Pronto quando:** Critério 1 da SPEC-007 §6 (queda no PA visível)

### P12.7 🤖 Escala divergente `mom_change`, estados de loading e erro, acessibilidade

- **Depende de:** P12.6
- **Pronto quando:** Critério 6 da SPEC-007 §6 + navegação por teclado

### P12.10 🤝 Spike: medir a latência do dashboard e avaliar o Lakebase como fonte de leitura

- **Depende de:** P12.7
- **Pronto quando:** Latência por endpoint (cache frio e quente, warehouse frio e quente) registrada; o teste de uma synced table do Lakebase com resultado; ADR com a decisão (adotar, descartar ou adotar só o plano mais barato)
- **Passos:**
  - Medir onde está o tempo: `/api/months`, `/api/kpis` e `/api/map/*` (região, UF, município), com o warehouse parado e aquecido, e a geometria de `geo/mun/<UF>.json`. Registrar em `docs/spikes/`
  - Avaliar as alternativas mais baratas primeiro: agregado pré-calculado derivado de `mv_recharges` e lido pelo warehouse, aquecimento do cache na subida do App com atualização em segundo plano, consultas do mapa agrupadas
  - Testar o Lakebase com **uma** tabela agregada: `databricks postgres create-synced-table` (modo `SNAPSHOT`) sobre um Delta derivado da metric view; conferir (1) se há cota para o projeto, (2) se o pipeline gerenciado da sync conflita com o limite de 1 pipeline ativo e o `atlas_medallion`, (3) a latência de leitura por `psycopg` contra a do warehouse
  - Conferir o princípio 1: o Postgres não executa `MEASURE()`, então o agregado só pode ser **derivado** da metric view (uma definição por métrica) e precisa morar em `semantic`
  - Escrever o ADR com pelo menos 2 alternativas descartadas. Adotar o Lakebase exige atualizar `tech-stack.md`, o ADR-0009 e a SPEC-007 §2 e §3 (commit `docs(specs)` anterior ao código) e abre uma task de implementação própria
  - Perfil e warehouse do `dev` ficam com o mantenedor; o agente prepara os scripts e as consultas

### P12.11 🤖 `sql_client` com conexão reaproveitada e aquecimento do cache

- **Depende de:** P12.10 (ADR-0022)
- **Pronto quando:** Testes unitários cobrem reconexão e threads; `scripts/spike_dashboard_latency.py reuse` mostra p50 < 500 ms; os `check_web_*` seguem ok no `dev`
- **Passos:**
  - Trocar o `make_executor` (hoje abre `Config()` e `dbsql.connect` a cada `execute`) por uma conexão por thread, aberta na 1ª consulta e reaproveitada; em erro de conexão, fechar, reabrir e tentar uma vez
  - Aquecer o cache na subida do App (as consultas da tela do último mês, em paralelo, sem bloquear a subida) e atualizar em segundo plano antes do TTL de 10 minutos
  - Manter parâmetros vinculados e o contrato de erros (`503 WAREHOUSE_UNAVAILABLE`) da SPEC-007 §3

### P12.8 🤝 Deploy do App `atlas-web` + medição de p95

- **Depende de:** P12.11
- **Pronto quando:** p95 < 3s registrado

### P12.9 🤝 Revalidar o production monitoring do MLflow (Beta) da P10.8

- **Depende de:** P12.8
- **Pronto quando:** O comando de contagem de assessments é rodado no `dev` e o resultado (mudou ou não) fica registrado na SPEC-008 §6 e no ADR-0013
- **Passos:**
  - Contexto: na P10.8 os 3 LLM judges foram registrados a 20% (`eval/start_monitoring.py`) e nenhum dos 20 traces recebeu assessment. O plano B (job `atlas_agent_monitoring`) é o caminho em uso. Esta task só verifica se algo mudou; não troca o caminho
  - Confirmar que os judges ainda estão registrados em `atlas_agent_traces` (se não, `start_monitoring.py --experiment-id <id> --start`)
  - Com tráfego novo no agente (algumas dezenas de perguntas), rodar a contagem de assessments: `MLFLOW_DISABLE_AGENT_HINT=1 MLFLOW_TRACING_SQL_WAREHOUSE_ID=<warehouse> DATABRICKS_CONFIG_PROFILE=<perfil> uv run --project apps/agent python -c "import mlflow; mlflow.set_tracking_uri('databricks'); ts=mlflow.search_traces(locations=['<id de atlas_agent_traces>'],return_type='list',max_results=200); print(len(ts), sum(bool(t.info.assessments) for t in ts))"`
  - Se continuar 0 assessments: registrar a nova data na SPEC-008 §6 e no ADR-0013 (o Beta segue sem efeito) e parar
  - Se houver assessments: registrar a latência trace→assessment e conferir que o job as reaproveita sem duplicar (deduplicação por nome); só então propor, em PR separado e com confirmação do mantenedor, mudar o texto da SPEC-008 §6 e do ADR-0013

### P12.12 🤖 ADR e spec do chat do agente dentro do dashboard

- **Depende de:** P12.8, P10.8
- **Pronto quando:** ADR aceito e specs atualizadas em commit `docs(specs)` anterior ao código
- **Passos:**
  - Decisão já tomada pelo mantenedor: o `atlas-web` **chama** o `atlas-agent` (3 Apps mantidos, ADR-0009). Alternativas descartadas a registrar: agente embutido no processo do `atlas-web` (soma permissões e reabre a opção 4 do ADR-0009) e link ou iframe para a chat UI do agente (fora do board)
  - Decidir e registrar: autenticação da chamada (token do usuário em OBO ou service principal do web), a permissão mínima do SP do `atlas-web` no `atlas-agent`, o contrato da rota (corpo, erros, timeout, tamanho máximo, streaming ou não) e o que o trace do agente grava sobre o usuário
  - Conferir os princípios: nenhuma métrica calculada no frontend nem no `atlas-web`; o web continua lendo só `semantic`; o agente segue somente leitura e com a citação `Fonte:`
  - Atualizar SPEC-007 (§2 arquitetura, §3 API, §4 comportamento do painel, §6 critérios) e, se o contrato do agente mudar, a SPEC-005. Se o ADR-0009 ou o `tech-stack.md` precisarem mudar, o motivo vai no ADR

### P12.13 🤖 Painel de chat no `atlas-web`

- **Depende de:** P12.12
- **Pronto quando:** Testes unitários e build verdes; o painel só exibe a resposta e a citação
- **Passos:**
  - Agente (SPEC-005 §4, ADR-0023): mascarador de fluxo para os deltas de texto (corte em fronteira de espaço, 40 caracteres retidos), com testes de CPF, telefone e e-mail de 60 caracteres cortados em qualquer posição; o `done` traz o texto completo mascarado
  - Backend: `POST /api/chat` em SSE conforme o ADR-0023 (`delta`, `done`, `error`), repassando o token do usuário e o `conversation_id`; limite de 10 mensagens por minuto por usuário; falhas viram o contrato da SPEC-007 §3 (sem inventar resposta)
  - Frontend: painel de chat recolhível (SPEC-007 §4) que acrescenta os `delta`, troca pelo `done` e tem botão "Parar"; estados de vazio, enviando e erro, e teclado; mostra a citação `Fonte:` e nunca calcula métrica
  - Testes: contrato (erro do agente, timeout por idle e total, mensagem vazia, limite de tamanho, 403, limite por usuário, fluxo cortado no meio) com o agente simulado; nada de SQL novo no `atlas-web`

### P12.14 🤝 Deploy, escopo OBO, `CAN_USE` dos usuários e conferência do chat

- **Depende de:** P12.13
- **Pronto quando:** OBO entre Apps confirmado no `dev`; o SP do `atlas-web` sem permissão no agente; uma pergunta do golden set pelo painel devolve o mesmo valor do agente; p95 do dashboard não piora
- **Passos:**
  - O agente prepara o bundle (`user_api_scopes` do `atlas-web`) e a lista de usuários com `CAN_USE` no `agent-atlas`; **primeiro confirma no `dev` o escopo de OBO entre Apps** (ADR-0023: se falhar, reabrir o ADR) e um `scripts/check_web_chat.py`; o mantenedor faz o deploy e roda a conferência no `dev`
  - Conferir GS-001 pelo painel (R$ 4.122.460,00) e uma recusa do golden set; o trace do agente mostra o usuário; os 3 Apps sobem juntos (auto-stop de 24h)
