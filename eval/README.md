# eval

Golden set e scorers do agente. Governado pela [SPEC-008](../docs/specs/008-agent-evaluation/spec.md).

## `golden_set.yaml` (P9.1)

30 casos: 20 `metric`, 5 `comparison` e 5 `refusal`. Cada caso guarda a SQL de referência, não o número; a SQL sempre devolve 1 valor (`AS value`) e lê só `atlas.semantic`. O catálogo `atlas` vira `atlas_dev` no `dev` (`scripts/check_golden_set.py`). Mês de referência: outubro de 2026.
