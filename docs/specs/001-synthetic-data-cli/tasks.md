# Tasks — 001-synthetic-data-cli

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 4 — Dados sintéticos

### P4.1 🤖 Esqueleto do pacote `cli/` (uv, Typer, `atlas-cli --help`, testes rodando no CI)

- **Depende de:** P3.8
- **Pronto quando:** `atlas-cli --help` lista os comandos; CI verde
- **Passos:**
  - Entry point `atlas-cli`
  - Códigos de saída da SPEC-001 §2 como enum

### P4.2 🤖 Snapshot da referência IBGE (`data/reference/municipalities_ibge.csv`) com população e DDD

- **Depende de:** P4.1
- **Pronto quando:** 5.570 linhas; teste de unicidade e de 7 dígitos
- **Passos:**
  - Script `scripts/build_reference.py` documentado (fonte pública, rodado uma vez)
  - Commitar o CSV gerado, não o script em runtime

### P4.3 🤖 `generate`: distributors + pos com pesos regionais

- **Depende de:** P4.2
- **Pronto quando:** Invariantes 3 e 4 da SPEC-001 passam
- **Passos:**
  - Seed via `numpy.random.Generator`

### P4.4 🤖 `generate`: recharges com valores de face, curva intradiária e status

- **Depende de:** P4.3
- **Pronto quando:** Invariantes 2 e 5 passam com `--scenarios none`
- **Passos:**
  - Partição por `dt=`
  - UUIDv5 determinístico

### P4.5 🤖 Sazonalidade (salário, dezembro, fevereiro, domingo)

- **Depende de:** P4.4
- **Pronto quando:** Teste estatístico simples de que os dias 5 a 10 têm volume > média

### P4.6 🤖 Cenários da SPEC-001 §5 + `_manifest.json` com contagens e sha256

- **Depende de:** P4.5
- **Pronto quando:** Os testes leem o manifest e conferem cada contagem
- **Passos:**
  - Um cenário por módulo; `scenario list`

### P4.7 🤖 `validate` + teste de determinismo (seed igual = sha igual)

- **Depende de:** P4.6
- **Pronto quando:** Critério 1 da SPEC-001 §7

### P4.8 🤖 `--incremental-day`

- **Depende de:** P4.7
- **Pronto quando:** Critério 3 da SPEC-001 §7

### P4.9 🤝 `upload` idempotente para `/Volumes/atlas/raw/landing/`

- **Depende de:** P4.8, P5.2
- **Pronto quando:** Critério 5 da SPEC-001 §7 (o agente implementa; você roda contra o workspace)
- **Passos:**
  - databricks-sdk Files API; comparar sha256
