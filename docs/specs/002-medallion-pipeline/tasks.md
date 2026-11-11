# Tasks — 002-medallion-pipeline

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 5 — Bundle e catálogo como código

### P5.1 🤖 `databricks.yml` com targets `dev`/`demo` e `bundle validate` no CI

- **Depende de:** P3.8
- **Pronto quando:** `databricks bundle validate -t dev` passa no CI

### P5.2 🤝 Catálogo `atlas`, schemas, Volume `raw.landing` e grupos `atlas_readers`, `atlas_commission_*`

- **Depende de:** P5.1
- **Pronto quando:** Deploy em `dev` feito por você; os objetos aparecem no Catalog Explorer
- **Passos:**
  - SQL de setup idempotente (`CREATE … IF NOT EXISTS`)

## Fase 6 — Pipeline medalhão

### P6.1 🤖 Bronze: Auto Loader de `recharges`, MVs de `pos`, `distributors`, `municipalities`

- **Depende de:** P4.9, P5.2
- **Pronto quando:** As contagens no bronze são iguais às do manifest

### P6.2 🤖 Silver `recharges`: dedup, `recharge_date` em America/Sao_Paulo, expectations drop/warn

- **Depende de:** P6.1
- **Pronto quando:** Critério 1 da SPEC-002 §5

### P6.3 🤖 Silver `recharges_quarantine` (PDV órfão)

- **Depende de:** P6.2
- **Pronto quando:** Critério 2 da SPEC-002 §5

### P6.4 🤖 Silver das dimensões com `expect_or_fail`

- **Depende de:** P6.1
- **Pronto quando:** Critério 4 da SPEC-002 §5 (teste com um PDV de município inválido)

### P6.5 🤖 Gold: `dim_*` + `fct_recharges` com COMMENT em tabelas e colunas

- **Depende de:** P6.3, P6.4
- **Pronto quando:** Linhagem visível; todas as colunas descritas

### P6.6 🤖 Gold `agg_pos_month`

- **Depende de:** P6.5
- **Pronto quando:** A soma bate com `fct_recharges` por mês

### P6.7 🤝 Job `atlas_daily` (06:00) + task de frescor em `observability.pipeline_freshness`

- **Depende de:** P6.6
- **Pronto quando:** Execução agendada termina antes das 08:00
