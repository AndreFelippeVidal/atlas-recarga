# ADR-0009 — Alocar os 3 slots de Databricks Apps em agente, MCP e React

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-005, SPEC-006, SPEC-007

## Contexto
A Free Edition permite **até 3 Apps por conta**, e cada App **para automaticamente 24h** depois de iniciado ou redeployado. Há três candidatos: o agente, o MCP e o dashboard React.

## Critérios de decisão
- Tudo governado pelo Databricks (auth e permissões via UC).
- Nenhum token de acesso a dados fora do workspace.
- Demo confiável apesar do auto-stop.

## Opções consideradas
1. **Três Apps: `atlas-agent`, `atlas-mcp`, `atlas-web`**
2. **React fora do Databricks** (Vercel ou local) chamando a API SQL, liberando 1 slot
3. **Agente como serving endpoint** (Model Serving) e não como App, liberando 1 slot
4. **Um App monolítico** com agente, MCP e web no mesmo processo

## Decisão
**Opção 1.** Cada componente tem o próprio ciclo de deploy, service principal e permissões mínimas.

## Prós e contras
**3 Apps.** 👍 Isolamento de permissão por componente; tudo dentro do Databricks. 👎 **Nenhum slot livre** para experimentos; três Apps para religar.
**React externo.** 👍 Sobra um slot. 👎 Token do workspace num host externo; a governança enfraquece.
**Agente como serving.** 👍 Sobra um slot. 👎 O padrão atual de agentes é o App; o serving de agente tem menos recursos de gateway (só inference tables).
**Monolito.** 👍 Um slot só. 👎 Um service principal com a soma das permissões; um deploy do React derruba o agente; o blast radius aumenta.

## Consequências
- **Positivas:** o menor privilégio é real (o SP do web só lê `semantic`; o do agente tem ainda o Genie).
- **Negativas aceitas:** o auto-stop de 24h. **Runbook de demo** no README: `make apps-start`, que roda `databricks apps start` nos 3 Apps e espera os healthchecks.
- **Revisitar se:** precisarmos de um 4º App (por exemplo, a UI de aprovação de comissão na v2). A primeira candidata a mesclar é a UI de aprovação dentro do `atlas-web`, com rotas e SP separados avaliados em novo ADR.
