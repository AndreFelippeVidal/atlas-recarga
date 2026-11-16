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
