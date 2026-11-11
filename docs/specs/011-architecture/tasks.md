# Tasks — 011-architecture

> Spec: [spec.md](spec.md) · Status de cada task: [roadmap](../roadmap.md) (único lugar com checkbox)
> Executor: 🤖 o agente de código executa sozinho · 🤝 o agente prepara, você executa ou aprova no workspace · 👤 só você

## Fase 2 — Arquitetura explicada

### P2.1 🤖 Escrever `docs/architecture.md` com o diagrama Mermaid (C4 nível 2)

- **Depende de:** P1.6
- **Pronto quando:** Revisado por PR; todos os componentes do PRD aparecem
- **Passos:**
  - Fluxo: CLI → Volume → pipeline → gold → semantic → consumidores
  - Destacar a fronteira do humano (comissão) e a fronteira da IA (só leitura)

### P2.2 🤖 Tabela de modos de falha por componente (o que quebra, o efeito, a detecção, a recuperação)

- **Depende de:** P2.1
- **Pronto quando:** Cada linha aponta para a spec que define o comportamento
- **Passos:**
  - Consolidar as seções "Falhas" das SPECs 002, 003, 005, 006 e 007
