---
description: Marca uma task como concluída no roadmap com o número do PR e roda o teste de higiene
argument-hint: <ID da task> <número do PR>  (ex.: P4.3 12)
---

Feche a task no roadmap seguindo a SPEC-010 §6. Argumentos: `$ARGUMENTS` (ID da task e número do PR).

1. Se faltar o ID ou o número do PR, pergunte e pare.
2. Em `docs/specs/roadmap.md`, localize a linha `- [ ] **<ID>**`. Se ela não existir ou já estiver `[x]`, informe e pare.
3. Troque `- [ ]` por `- [x]` e insira ` (#<PR>)` logo antes de ` · depende de` (ou no fim da linha, se não houver dependências). O formato tem de ser **exatamente** `(#N)`.
4. Rode `uv run pytest tests/test_repo_hygiene.py` e mostre o resultado.
5. **Não faça commit, push nem merge**: a mudança entra no próprio PR da task, e o merge é do mantenedor (ADR-0014).
