# ADR-0001 — Usar o Databricks Free Edition como plataforma única

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-002, ADR-0009

## Contexto
O produto precisa de ingestão, transformação com linhagem, camada semântica, BI, agente de IA governado e MCP. É um projeto de portfólio: custo zero e demo reproduzível. O desafio pede uma arquitetura defensável, não uma infraestrutura cara.

## Critérios de decisão
- Custo de R$ 0.
- Governança e linhagem nativas, sem montar ferramentas separadas.
- IA (LLM, agente, tracing, avaliação) no mesmo plano de governança dos dados.
- Proximidade com o que o mercado usa em produção.

## Opções consideradas
1. **Databricks Free Edition**
2. **Stack local open source:** DuckDB + dbt-core + Streamlit + LLM via API externa
3. **Cloud gerenciada com créditos de trial** (BigQuery ou Snowflake trial + Vertex ou Cortex)

## Decisão
**Databricks Free Edition.** É a única opção que entrega Unity Catalog (linhagem e permissões), Lakeflow, metric views, Genie, Apps, MLflow 3 e Unity Gateway no mesmo lugar e sem custo.

## Prós e contras
**Free Edition.** 👍 Governança ponta a ponta; IA e dados sob as mesmas permissões; deploy via Asset Bundles. 👎 Limites rígidos: 1 SQL warehouse 2X-Small, 1 pipeline ativo por tipo, 5 job tasks concorrentes, **até 3 Apps que param após 24h**, serving sem GPU, alguns modelos indisponíveis; e recursos em Beta podem não estar liberados.
**Stack local.** 👍 Controle total, roda offline. 👎 Linhagem, permissões, tracing e gateway de LLM teriam de ser montados à mão; não demonstra governança de IA.
**Trial de cloud.** 👍 Sem limites artificiais. 👎 Os créditos expiram e a demo morre; risco de cobrança real.

## Consequências
- **Positivas:** uma só fronteira de segurança; linhagem visível do landing até a metric view.
- **Negativas aceitas:** o design é moldado pelas cotas (ADR-0009). Os recursos Beta exigem o Spike S0 e um plano B registrado. Não há escala real para testar desempenho.
- **Cotas na prática:** o S0.7 (2026-11-12) rodou 2M de recargas (bronze + silver, serverless) em 113 s, sem erro de cota. O `--rows` padrão de 2M se mantém. Ressalva: foi um teste em lote, sem Auto Loader e sem a concorrência do pipeline completo; isso só se mede na P6.7 (ver `docs/spikes/S0-results.md`, S0.7).
- **Revisitar se:** a Free Edition remover algum recurso essencial (Apps, metric views, Unity Gateway) ou o projeto migrar para um workspace pago.
