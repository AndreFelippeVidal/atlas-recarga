# PRD — Atlas Recarga v1 (MVP)

> Status: **validado** · Última atualização: 2026-11-11 · Base: [discovery.md](discovery.md)

## 1. Objetivo

Dar à Diretoria Comercial da Eaí? Telecom uma visão **confiável, D-1 e geográfica** da rede de recarga, **fechar a comissão de canal com revisão humana e trilha de auditoria**, e permitir **perguntas de negócio em linguagem natural** com respostas rastreáveis até a definição da métrica.

## 2. Personas e jornadas

| Persona | Jornada principal no MVP |
|---|---|
| **Helena Duarte**, Diretora Comercial | Abre o dashboard React → vê o mapa do Brasil por receita → clica no PA → vê os municípios do oeste em vermelho → pergunta ao agente "por que a recarga caiu em Santarém em outubro?" → recebe o número, a metric view usada e a comparação com o mês anterior |
| **Analista de Comissões** | O pipeline fecha o mês → o lote nasce em `draft` com o relatório de reconciliação → ela revisa divergências e outliers → aprova ou rejeita com justificativa → Helena dá o aval final → o lote vira `locked` e gera a remessa simulada |
| **Gerente Regional** | Filtra a própria UF no AI/BI dashboard → acompanha PDVs ativos e ticket médio por município |
| **Helena no Claude** | Conecta o MCP Atlas no Claude → pergunta "top 10 municípios por receita no Nordeste em setembro" → recebe a resposta a partir das metric views |

## 3. Escopo da v1

### Entra

| # | Capacidade | SPEC |
|---|---|---|
| F1 | **CLI de dados sintéticos**: recargas, PDVs, distribuidores e municípios com código IBGE. ~2M recargas / 12 meses por padrão, seed determinística, anomalias injetadas | [SPEC-001](specs/001-synthetic-data-cli/spec.md) |
| F2 | **Pipeline medalhão** em Lakeflow Spark Declarative Pipelines, com bronze/silver/gold no Unity Catalog, linhagem nativa e expectations básicas | [SPEC-002](specs/002-medallion-pipeline/spec.md) |
| F3 | **Fechamento de comissão** determinístico, com reconciliação independente, estados `draft → under_review → approved/rejected → locked`, aprovação humana em duas etapas e lote imutável | [SPEC-003](specs/003-commission-closing/spec.md) |
| F4 | **Metric views** como camada semântica única (receita, recargas, ticket médio, PDVs ativos, comissão) | [SPEC-004](specs/004-metric-views/spec.md) |
| F5 | **AI/BI Dashboard** e **Genie Space** sobre as metric views | [SPEC-004](specs/004-metric-views/spec.md) |
| F6 | **Agente de negócio** (Mosaic AI Agent Framework + Genie), só leitura, com citação da fonte, MLflow tracing e LLM atrás do **Unity Gateway** | [SPEC-005](specs/005-business-agent/spec.md) |
| F7 | **MCP server FastMCP** em Databricks App, conectável ao Claude | [SPEC-006](specs/006-mcp-server/spec.md) |
| F8 | **Dashboard React** em Databricks App: KPIs, mapa coroplético por UF e drill-down municipal | [SPEC-007](specs/007-react-geo-dashboard/spec.md) |
| F9 | **Avaliação e monitoramento do agente** com MLflow 3 GenAI: golden set versionado no UC, scorers determinísticos e LLM judges, gate de acurácia no PR, monitoramento contínuo dos traces e ciclo de falha → golden set | [SPEC-008](specs/008-agent-evaluation/spec.md) |

### Fica de fora (e por quê)

| Item | Por que não agora | Quando |
|---|---|---|
| Forecast e metas regionais | Exige histórico confiável e backtesting. Uma meta errada desmotiva o canal. | v2 |
| Geo híbrido (CEP → IBGE cacheado) | O código IBGE nativo basta para o mapa. A API de CEP adiciona latência e um ponto de falha. | Logo após o MVP |
| Personas do agente (Helena, Analista, Regional) | Primeiro é preciso provar a acurácia de um agente genérico | v2 |
| Lakehouse Monitoring e DQ avançado | O MVP prova o fluxo de ponta a ponta; o DQ entra por camada depois | v2 |
| Pagamento real ou integração bancária | Restrição do desafio: nenhum efeito externo. A remessa é simulada. | Nunca |
| IA no cálculo ou na aprovação de comissão | Etapa irreversível. Decisão deliberada de manter determinístico e humano. | Nunca no escopo atual |
| Controle de acesso por região (row-level security) | Um só usuário na Free Edition, então não há como demonstrar | v3 |
| Dados intradiários ou streaming | D-1 atende à dor (hoje é D+7). Streaming consumiria a cota da Free Edition. | v3, se houver demanda |

## 4. Métricas de sucesso

| Dimensão | Métrica | Meta v1 | Como medir |
|---|---|---|---|
| **Confiança do agente** | Acurácia no golden set | **≥ 90%** em ~30 perguntas | `mlflow.genai.evaluate` contra respostas esperadas, calculadas via SQL nas metric views |
| | Respostas que citam a fonte | **100%** | Verificação no trace: toda resposta numérica referencia a metric view usada |
| | Recusa fora do escopo | **100%** em ~5 perguntas adversariais | Casos no golden set (ex.: "aprove a comissão", "qual o CPF do PDV X") |
| | Regressão bloqueada | **0** merges que derrubem a acurácia para menos de 90% | Gate de avaliação no CI para PRs que mexem em agente, prompt ou metric view |
| | Qualidade em produção | Média móvel de 7 dias **≥ 90%** nos scorers determinísticos | Monitoramento de traces (SPEC-008). Uma queda abre um item de investigação. |
| **Comissão** | Divergência entre o cálculo e a reconciliação independente | **R$ 0,00** | Teste automatizado por lote |
| | Lotes `locked` com aprovador registrado nas 2 etapas | **100%** | Consulta na tabela de auditoria |
| **Frescor e desempenho** | Gold D-1 disponível | **até 08:00** | Horário de término do job agendado |
| | Dashboard React | **p95 < 3s** por interação | Medição no browser e logs do App |
| | Agente | **p95 < 15s** | MLflow traces |
| **Valor para a Helena** | Tempo de fechamento de comissão | **~3 dias → < 1h** | Tempo do pipeline somado ao tempo de revisão humana (simulado) |
| | Tempo para responder a uma pergunta ad hoc | **dias → < 1 min** | Latência do agente |
| **Consistência** | Mesmo número no agente, no AI/BI e no React | **100%** das métricas do golden set | Teste cruzado |

## 5. Requisitos não funcionais

- **Plataforma:** Databricks Free Edition, respeitando o limite de 3 Apps, 1 SQL warehouse 2X-Small e 1 pipeline ativo por tipo.
- **Governança:** tudo no Unity Catalog (catálogo `atlas`), com linhagem visível de bronze até a metric view.
- **Segurança:** nenhum segredo no repositório (Databricks secrets e variáveis de ambiente do App). Agente e MCP somente leitura.
- **Reprodutibilidade:** o CLI com `--seed` gera exatamente o mesmo dataset. O deploy é feito via Databricks Asset Bundles.
- **Observabilidade:** MLflow tracing no agente, uso e inference tables do Unity Gateway (`system.ai_gateway.usage`) e logs dos Apps.

## 6. Riscos

| Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|
| Uma feature necessária não estar disponível ou estar limitada na Free Edition | Média | Alto | Validar cada feature na doc antes da SPEC e registrar o plano B no ADR |
| Os Apps pararem após 24h durante a demo | Alta | Médio | Runbook de "start" antes da demo, documentado no ADR-0009 |
| Agente com acurácia < 90% | Média | Alto | Iterar nas instruções do Genie e nas descrições das metric views, guiado pelo golden set |
| Cota de compute estourar com 2M de linhas | Baixa | Médio | Flag `--rows` no CLI e geração incremental por mês |
| Production monitoring (Beta) indisponível na Free Edition | Média | Médio | Plano B: job agendado com `mlflow.search_traces` + `mlflow.genai.evaluate` sobre uma amostra dos traces do dia (ADR-0013) |
| LLM judges consumirem a cota de foundation models | Média | Baixo | Scorers determinísticos em 100% dos traces; LLM judges só numa amostra de 20% |

## 7. Roadmap

| Versão | Foco |
|---|---|
| **v1 (MVP)** | F1–F8 de ponta a ponta |
| **v1.1** | Geo híbrido (CEP → IBGE em tabela de referência cacheada) |
| **v2** | Forecast e metas regionais, personas do agente, DQ por camada e Lakehouse Monitoring |
| **v3** | Row-level security por região, alertas proativos de queda regional, ingestão intradiária |

## 8. Critério de "pronto" da v1

A demo de ponta a ponta roda a partir do README: `atlas-cli generate` → deploy do bundle → pipeline popula o gold → um lote de comissão passa pelas 2 aprovações e vira `locked` → o mapa React mostra o drill-down UF → município → o agente e o MCP no Claude respondem a uma pergunta do golden set citando a fonte. Todas as métricas da seção 4 são medidas e publicadas no README.
