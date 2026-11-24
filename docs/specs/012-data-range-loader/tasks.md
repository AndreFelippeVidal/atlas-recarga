# Tasks — 012-data-range-loader

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 14 — Carga de dados por intervalo

### P14.1 🤖 `atlas_cli.prune` + `scripts/load_data.py` (gera, poda, valida, envia e roda o `atlas_daily`)

- **Depende de:** P13.2
- **Pronto quando:** Critérios 1 a 5 da SPEC-012 §6, com testes sem workspace; o mantenedor confere o critério 6 no `dev`
- **Passos:**
  - `cli/src/atlas_cli/prune.py`: `prune_recharges(out, first, last)` remove `dt=` fora do intervalo, atualiza `files`, `counts` e a chave `pruned` do manifest; o `validate` pula o invariante 5 quando há `pruned`
  - `scripts/load_data.py`: plano, janela base fixa, `--incremental-day` fora dela, poda, `validate`, checagem de `pos`/`distributors` contra o manifest remoto, `upload`, `bundle run atlas_daily`
  - Testes: poda (contagens e sha256 do manifest), plano (dentro e fora da janela), checagem de PDV divergente, flags inválidas, `--dry-run`
  - `scripts/README.md` com o comando
