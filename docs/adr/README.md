# ADRs — Atlas Recarga

Formato [MADR](https://adr.github.io/madr/). Cada ADR registra o contexto, **pelo menos 2 alternativas descartadas**, a decisão e as consequências aceitas. Template: [0000](0000-template.md).

| # | Decisão | Status |
|---|---|---|
| [0001](0001-databricks-free-edition.md) | Databricks Free Edition como plataforma única | aceito |
| [0002](0002-lakeflow-declarative-pipelines.md) | Lakeflow Spark Declarative Pipelines para o medalhão | aceito |
| [0003](0003-medallion-unity-catalog.md) | Catálogo `atlas` em medalhão + schemas de propósito | aceito |
| [0004](0004-ibge-code-geojson-geo.md) | Código IBGE + malha GeoJSON; CEP híbrido na v1.1 | aceito |
| [0005](0005-metric-views-semantic-layer.md) | Metric views como camada semântica única | aceito |
| [0006](0006-agent-framework-genie.md) | Agent Framework com Genie como ferramenta | aceito |
| [0007](0007-unity-gateway-llm-governance.md) | Tráfego de IA governado pelo Unity Gateway | aceito (Spike S0.1/S0.2) |
| [0008](0008-fastmcp-on-databricks-apps.md) | MCP próprio com FastMCP em Databricks App | aceito |
| [0009](0009-three-apps-allocation.md) | 3 slots de App: agente, MCP, React | aceito |
| [0010](0010-commission-human-in-the-loop.md) | Comissão: determinística, 2 aprovações, lote imutável | aceito |
| [0011](0011-deterministic-synthetic-cli.md) | CLI sintético determinístico com cenários | aceito |
| [0012](0012-claude-code-harness.md) | Claude Code como harness, com limites por hook | aceito |
| [0013](0013-mlflow-genai-evaluation-monitoring.md) | Avaliação e monitoramento com MLflow 3 GenAI | aceito (Spike S0.3) |
| [0014](0014-branch-protection-solo-maintainer.md) | Proteção da `main`: PR + checks, 0 aprovações (mantenedor único) | aceito |
| [0015](0015-ci-databricks-auth.md) | Auth do `bundle validate` no CI: secrets num GitHub Environment | aceito |
| [0016](0016-uc-grants-per-principal.md) | Grants no Unity Catalog por principal, não por grupo de workspace | proposto |
