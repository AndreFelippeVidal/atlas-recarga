---
description: Encontra a próxima task aberta do roadmap e propõe como começá-la (não começa sozinho)
---

Encontre a próxima task do Atlas Recarga seguindo a SPEC-010 §6.

1. Leia `docs/specs/roadmap.md`. Cada task é uma linha `- [ ] **P<fase>.<n>** <executor> <título> — _pronto quando:_ … · depende de …`.
2. A próxima task é a **primeira** linha `- [ ]` em que **todas** as tasks listadas em "depende de" estão marcadas `- [x]`. Uma linha sem "depende de" não tem dependências.
3. Descubra a spec da task: é o link na linha `## Fase N — … → [NNN-nome](NNN-nome/spec.md)` da fase em que ela está. Abra `docs/specs/NNN-nome/tasks.md` e localize a seção `### <ID>`.
4. Responda **só** com:
   - **Task:** ID e título
   - **Executor:** 🤖, 🤝 ou 👤
   - **Spec:** caminho do `spec.md` e as seções relevantes
   - **Pronto quando:** o critério
   - **Passos:** os do `tasks.md`
   - **Branch proposta:** `task/<ID>-<slug-curto-em-ingles>`
5. **Se o executor for 👤**, diga que a task é exclusiva do mantenedor, explique o que ele precisa fazer e **pare**. Não proponha branch.
6. **Não crie a branch nem altere arquivos.** Espere o mantenedor confirmar.

$ARGUMENTS
