# SPEC-011 — Arquitetura explicada

> Roadmap: Fase 2 · PRD: F1–F9 · ADRs: [0001](../../adr/0001-databricks-free-edition.md), [0003](../../adr/0003-medallion-unity-catalog.md), [0009](../../adr/0009-three-apps-allocation.md), [0010](../../adr/0010-commission-human-in-the-loop.md) · Status: rascunho

## 1. Objetivo
Um desenho e um texto curto explicando como o sistema se sustenta: os componentes, onde ficam os dados, onde entra a IA, onde entra o humano e o que acontece quando algo falha no meio do caminho. O leitor é quem avalia o projeto e o próprio agente de código: ninguém precisa ler as 10 specs para entender o todo.

## 2. Entregável
Um único arquivo, `docs/architecture.md`, que **não define comportamento novo**. Ele resume e aponta para as specs; quando os dois divergirem, vale a spec, e o `architecture.md` é corrigido.

| Seção | Conteúdo | Task |
|---|---|---|
| Visão em uma frase | O fluxo de ponta a ponta | P2.1 |
| Diagrama de containers (C4 nível 2) | Pessoas, sistemas externos e containers do workspace, com a tecnologia de cada um | P2.1 |
| Onde ficam os dados | Um schema do catálogo `atlas` por linha: o que guarda, quem escreve, quem lê | P2.1 |
| Fronteira do humano | O caminho do lote de comissão até o `locked`, com o que nenhuma máquina pode fazer | P2.1 |
| Fronteira da IA | O que agente e MCP alcançam e o que fica fora do alcance, em camadas | P2.1 |
| Componentes | Uma linha por componente: PRD (F1–F9), spec, ADR, onde está no repo | P2.1 |
| Limites da Free Edition | Quais limites moldam o desenho e como | P2.1 |
| Modos de falha | O que quebra, efeito, detecção, recuperação, com a spec de origem | P2.2 |

## 3. Regras
- **Mermaid** renderizado pelo GitHub. O C4 nível 2 é desenhado com `flowchart` e subgrafos como fronteiras, rotulando cada caixa como `[Container: tecnologia]`. O tipo `C4Container` do Mermaid é experimental e tem layout fraco no GitHub.
- **Todo componente do PRD aparece** no diagrama e na tabela de componentes. Um teste de higiene confere que `architecture.md` cita F1–F9 e as SPECs 001–008.
- Nomes de objetos (tabelas, jobs, Apps, schemas) iguais aos das specs, em `código`.
- Até ~250 linhas; detalhes ficam nas specs.

## 4. Critérios de aceite
- **Dado** o PRD, **então** cada capacidade F1–F9 aparece no diagrama e na tabela de componentes, com link para a spec.
- **Dado** o diagrama, **então** a fronteira do humano (comissão) e a fronteira da IA (só `atlas.semantic`) estão destacadas visualmente.
- **Dado** os schemas do ADR-0003, **então** cada um aparece em "Onde ficam os dados" com escritor e leitores.
- **Dado** `uv run pytest`, **então** o teste de cobertura do `architecture.md` passa.
- **(P2.2) Dado** as seções de falha das SPECs 002, 003, 005, 006 e 007, **então** cada linha delas aparece na tabela de modos de falha, apontando para a spec.

## 5. Fora de escopo
Diagramas de sequência por feature (ficam nas specs), C4 nível 3 e 4, diagrama de deploy do bundle (P5.1).
