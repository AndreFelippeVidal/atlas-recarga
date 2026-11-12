# Tech stack — Atlas Recarga

> Constituição do projeto, parte 2 de 3 · [mission](mission.md) · [tech-stack](tech-stack.md) · [roadmap](roadmap.md)
> Adicionar, trocar ou remover uma tecnologia desta tabela exige um ADR. As versões exatas ficam fixadas nos lockfiles (`uv.lock`, `pnpm-lock.yaml`). Aqui fica a **versão mínima** e a regra de atualização.

## Stack por camada

| Camada | Tecnologia | Versão mínima | ADR | Observação |
|---|---|---|---|---|
| Plataforma | Databricks Free Edition (serverless) | — | 0001 | Cotas: 1 SQL warehouse 2X-Small · 1 pipeline ativo por tipo · 5 job tasks concorrentes · 3 Apps (auto-stop de 24h) |
| Governança | Unity Catalog, catálogo `atlas` | — | 0003 | Schemas: `raw, bronze, silver, gold, semantic, commission, eval, observability` |
| Deploy | Databricks Asset Bundles + Databricks CLI | CLI ≥ 0.260 | 0001 | Targets `dev` (catálogo `atlas_dev`) e `demo` (`atlas`) |
| Dados sintéticos | `atlas-cli`: Python + Typer + NumPy + PyArrow; `databricks-sdk` (Files API) só no `upload` | Python 3.12 | 0011 | Seed determinística; Faker `pt_BR` só para nomes fictícios |
| Ingestão e transformação | Lakeflow Spark Declarative Pipelines (`from pyspark import pipelines as dp`) + Auto Loader | Canal current do pipeline serverless | 0002 | Um único pipeline `atlas_medallion` |
| Orquestração | Lakeflow Jobs | — | 0002 | `atlas_daily`, `atlas_commission_review`, `atlas_agent_monitoring` |
| Camada semântica | UC metric views (`WITH METRICS LANGUAGE YAML`) | YAML `version: 1.1` | 0005 | Fonte de verdade em `semantic/*.yaml` |
| BI | AI/BI Dashboards + Genie Space | — | 0005 | Só sobre metric views |
| Agente | Mosaic AI Agent Framework: LangGraph + `databricks-langchain` em Databricks App | MLflow ≥ 3.x | 0006 | `ChatDatabricks(use_ai_gateway=True)` |
| Governança de IA | Unity Gateway (model service; agent service em Beta) · plano B: AI Gateway clássico | — | 0007 | Alternável por `ATLAS_GATEWAY_MODE` |
| Avaliação | MLflow 3 GenAI (`mlflow.genai.evaluate`, scorers, production monitoring) | MLflow ≥ 3.x | 0013 | Golden set em `atlas.eval` |
| MCP | FastMCP (Streamable HTTP) em Databricks App + MLflow tracing manual (spans só com atributos) | FastMCP ≥ 2.x · MLflow ≥ 3.x | 0008 | Path `/mcp`; rate limit e auditoria no App (SPEC-006 §6) |
| Backend web | FastAPI + `databricks-sql-connector` | Python 3.12 | 0009 | Serve o build do React e `/api/*` |
| Frontend | React 18 + TypeScript + Vite + `d3-geo` | Node 22 LTS | 0004, 0009 | SVG, sem tiles nem chaves externas |
| Geometria | Malhas do IBGE (API v3) simplificadas com mapshaper, versionadas em TopoJSON | — | 0004 | Baixadas no build, nunca em runtime |
| Harness | Claude Code (`CLAUDE.md`, `.claude/settings.json`, hooks, commands) | — | 0012 | |

## Ferramentas de desenvolvimento

| Uso | Python | Web |
|---|---|---|
| Pacotes e ambiente | `uv` (workspace) | `pnpm` |
| Lint e format | `ruff` (lint + format) | `eslint` + `prettier` |
| Tipos | `mypy --strict` nos pacotes `src/` | `tsc --noEmit` (`strict: true`) |
| Testes | `pytest` (+ `pytest-cov`, meta ≥ 80% em `cli` e `commission`) | `vitest` + Testing Library |
| Segurança | `gitleaks` (segredos), `pip-audit` | `pnpm audit` |
| Docs | Checagem de links markdown (`lychee`) | — |
| Hooks locais | `pre-commit` (ruff, gitleaks, end-of-file) | — |
| Commits | Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`) | |

## Convenções globais
- **Nomes:** código, tabelas e colunas em inglês e `snake_case`; documentação em PT-BR.
- **Dinheiro:** `DECIMAL(14,2)` em BRL. Arredondamento `ROUND_HALF_EVEN` por linha.
- **Tempo:** timestamps em UTC (`*_ts_utc`); datas de negócio (`*_date`) e "mês" no fuso `America/Sao_Paulo`, mês civil.
- **Geo:** `municipality_ibge_code STRING` de 7 dígitos, com zeros preservados.
- **Configuração:** variáveis `ATLAS_*`; os segredos ficam em Databricks secrets (scope `atlas`) ou nos recursos do bundle e nunca no repositório.

## Proibido
| Não fazer | Por quê | Fonte |
|---|---|---|
| `DOUBLE` ou `FLOAT` para dinheiro | Erro de arredondamento na comissão | SPEC-003 |
| SQL livre em tools do agente ou do MCP | Injeção e quebra do menor privilégio | SPEC-005, SPEC-006 |
| Consumidor lendo `gold`, `silver`, `bronze` ou `commission` | Quebra o princípio 1 | mission.md |
| Chamada a API externa no pipeline | Acoplamento e falha em runtime | ADR-0004 |
| Métrica calculada no frontend ou no prompt | Duas definições da mesma métrica | ADR-0005 |
| `UPDATE` ou `DELETE` em `commission.locked_lines` ou `batch_events` | Imutabilidade do que foi "pago" | ADR-0010 |
| Dados reais, PII ou números de telefone com formato real | Restrição do desafio | ADR-0011 |
| Token, `.env` ou credencial versionados | Segredos fora do repo, sempre | — |
| Dependência nova sem atualizar esta tabela (quando estrutural) | Stack não documentada | este arquivo |

## Política de atualização
- Patch e minor: Dependabot (ou equivalente) abre o PR, o CI verde é obrigatório e o merge passa por revisão humana.
- Major ou troca de tecnologia: um ADR novo antes do PR.
