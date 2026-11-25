# Tasks — 004-metric-views

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 7 — Camada semântica (recargas)

### P7.1 🤖 `semantic/mv_recharges.yaml` + deploy

- **Depende de:** P6.5
- **Pronto quando:** `SELECT MEASURE(gross_revenue)` funciona

### P7.2 🤖 Teste de consistência metric view × SQL direto no gold

- **Depende de:** P7.1
- **Pronto quando:** Critério 1 da SPEC-004 §8

### P7.3 🤝 Grants: `atlas_readers` só em `semantic` + teste de PERMISSION_DENIED

- **Depende de:** P7.1
- **Pronto quando:** Critério 4 da SPEC-004 §8

### P7.4 🤝 AI/BI Dashboard "Atlas — Visão Comercial" (páginas Brasil, UF, Rede)

- **Depende de:** P7.1
- **Pronto quando:** Publicado; filtros de mês, região e UF
- **Passos:**
  - Versionar o `.lvdash.json` no bundle

### P7.5 🤝 Genie Space "Atlas Recarga" com instruções e 10 exemplos

- **Depende de:** P7.1
- **Pronto quando:** Critério 5 da SPEC-004 §8

### P7.6 🤝 Descrever `region` como código (N, NE, CO, SE, S) no COMMENT do gold e nas metric views

- **Depende de:** P7.5
- **Pronto quando:** O COMMENT de `dim_municipality.region` e o comment da dimensão `region` em `mv_recharges` e `mv_commission` listam os códigos; `check_mv_recharges.py` e `check_mv_commission.py` continuam ok no `dev`
- **Contexto:** o dado guarda `N`, `NE`, `CO`, `SE` e `S` (`data/reference/municipalities_ibge.csv`), mas os textos diziam "Norte, Nordeste…". Um filtro por nome (`region = 'Sul'`) volta nulo ou 0. Achado na P9.1 (#61).
- **Passos:** (1) corrigir os três textos; (2) o mantenedor roda o job do pipeline (para o COMMENT do gold) e `atlas_semantic_deploy` no `dev`; (3) conferir com os scripts acima.

## Fase 15 — Dashboard analítico (v1.1)

### P15.2 🤝 Spike: medidas com janela na `mv_recharges` (Free Edition)

- **Depende de:** P15.1
- **Pronto quando:** `docs/spikes/P15.2-window-measures.md` registra cada item abaixo e o ADR-0025 está `aceito` com pelo menos 2 alternativas descartadas
- **Passos:**
  - O agente prepara `scripts/spike_window_measures.py` e um YAML de teste numa metric view descartável (`atlas_dev.semantic.mv_recharges_window_spike`); o mantenedor roda no `dev` e apaga a view
  - Registrar: (1) `window` é aceito com `version: 1.1`, junto de `synonyms` e `format`? (2) `WHERE recharge_month = M` mantém a janela, **inclusive quando a consulta agrupa por `region`, `uf` ou `municipality_ibge_code` e não por `recharge_month`**? (a SPEC-007 depende disso) (3) o que `trailing N month` inclui: o mês atual entra? (4) o YTD zera em janeiro? (5) `revenue_mom_change` dá `NULL`, sem erro, sem mês anterior e com base zero? (6) `pos_type` e `distributor_name` no `WHERE` aplicam antes da janela? (7) o tempo da consulta com janela contra a sem janela
  - Cada resultado é conferido contra o SQL direto no gold (SPEC-004 §8)
  - ADR-0025 com a decisão: janelas na `mv_recharges`, view separada `mv_recharges_trend` (`version: 0.1`) ou manter a conta no backend; se a decisão mudar a SPEC-004 §5, a correção vai em commit `docs(specs)` anterior

### P15.5 🤖 `mv_recharges.yaml` com `gross_revenue_t3m`, `gross_revenue_ytd` e `revenue_mom_change`

- **Depende de:** P15.2
- **Pronto quando:** Os 3 critérios novos da SPEC-004 §8 passam no `dev` (a conferência fica com o mantenedor); o que a task faz depende do ramo do ADR-0025 (SPEC-004 §5)
- **Passos:**
  - Medidas no YAML (ou na view que o ADR-0025 escolher), com `comment` literal, `synonyms` e `format`
  - `scripts/check_mv_windows.py`: compara cada medida com o SQL direto no gold para os 12 meses, em 3 recortes (sem filtro, `pos_type`, `distributor`); janeiro e o primeiro mês da série incluídos
  - Teste unitário do script com warehouse simulado; `check_mv_recharges.py` segue ok

### P15.6 🤖 Janelas nos consumidores: catálogo do MCP, UC functions do agente e golden set

- **Depende de:** P15.5
- **Pronto quando:** `query_metric` e as UC functions aceitam as 3 medidas pela regra definida no spike (ex.: só agrupadas por `recharge_month`), com `INVALID_ARGUMENT` fora dela; o golden set ganha 3 casos (`GS-032` a `GS-034`: T3M, YTD, variação) com `reference_sql` que executa e retorna 1 valor; o Genie ganha 3 exemplos
- **Passos:**
  - **Antes do código**, commit `docs(specs)` atualizando a SPEC-005 (`fn_*`), a SPEC-006 (lista fechada de views e medidas, e a regra de consulta do spike) e a SPEC-008 (casos novos e o "~30"); nada de código antes disso
  - Regenerar `catalog.json` do MCP a partir do YAML (o teste `test_mcp_catalog_fresh` confere); `fn_*` geradas do YAML
  - Casos novos em `eval/golden_set.yaml` e no sync (SPEC-008); a acurácia do gate de CI não pode cair abaixo de 90%
  - O mantenedor confere `check_mcp_parity.py` e `check_agent_functions.py` no `dev`
