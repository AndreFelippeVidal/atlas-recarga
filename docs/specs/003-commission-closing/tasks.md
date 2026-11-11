# Tasks — 003-commission-closing

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 8 — Fechamento de comissão

### P8.1 🤖 `commission/rules.py` (faixas, taxas, arredondamento) + testes de borda

- **Depende de:** P6.6
- **Pronto quando:** Critério 2 da SPEC-003 §8; cobertura ≥ 95% no módulo
- **Passos:**
  - CODEOWNERS se aplica a partir daqui

### P8.2 🤖 Tabelas `commission.*` com `delta.appendOnly` em `batch_events` e `locked_lines`

- **Depende de:** P8.1
- **Pronto quando:** Teste: um UPDATE é rejeitado

### P8.3 🤖 Cálculo do rascunho (`draft`) em PySpark

- **Depende de:** P8.2
- **Pronto quando:** Lote `COM-YYYY-MM-v1` criado para o último mês fechado

### P8.4 🤖 Reconciliação independente em SQL + totais de controle

- **Depende de:** P8.3
- **Pronto quando:** Critério 1 da SPEC-003 §8 (R$ 0,00)

### P8.5 🤖 Flags de revisão (`spike_3x`, `fractioning_suspect`, `tier_jump`, `closed_pos`)

- **Depende de:** P8.4
- **Pronto quando:** Critério 3 da SPEC-003 §8

### P8.6 🤖 Job `atlas_commission_review`: máquina de estados, segregação de funções, justificativa

- **Depende de:** P8.5
- **Pronto quando:** Critérios 4 e 6 da SPEC-003 §8
- **Passos:**
  - Erros `SEGREGATION_OF_DUTIES_VIOLATION`, `JUSTIFICATION_REQUIRED`

### P8.7 🤖 Lock + remessa simulada + sha256

- **Depende de:** P8.6
- **Pronto quando:** Critério 7 da SPEC-003 §8

### P8.8 🤖 Dashboard/notebook `commission_review`

- **Depende de:** P8.5
- **Pronto quando:** A analista vê os totais, o top 20, os flags e a comparação com o mês anterior

### P8.9 👤 Primeiro fechamento ponta a ponta (você aprova nas 2 etapas)

- **Depende de:** P8.7, P8.8
- **Pronto quando:** Lote `locked` com 2 eventos de aprovação
- **Passos:**
  - O agente de código nunca executa esta task

### P8.10 🤖 Lote de ajuste `ADJ`

- **Depende de:** P8.7
- **Pronto quando:** SPEC-003 §7 coberto por teste

### P8.11 🤖 `semantic/mv_commission.yaml` (só `locked`) + página Comissão no AI/BI

- **Depende de:** P8.9
- **Pronto quando:** Critério 2 da SPEC-004 §8
