# ADR-0008 — MCP próprio com FastMCP hospedado em Databricks App

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-006, ADR-0007, ADR-0009

## Contexto
A Helena quer perguntar sobre os dados direto do Claude. Um requisito do projeto é um MCP com **FastMCP**, criado **dentro do Databricks**. A documentação mostra duas restrições:
- Um MCP customizado pode ser hospedado em Databricks Apps (Streamable HTTP em `/mcp`).
- **Um MCP em Databricks Apps não pode ser registrado como MCP Service do Unity Gateway.** O registro vale só para MCPs externos via conexão HTTP; para Apps, a orientação é conectar direto ao servidor.

## Critérios de decisão
- Mesma camada semântica e mesmas regras do agente (só leitura, lista fechada, citação).
- Hospedado e autenticado pelo Databricks, sem token no repositório.
- Ferramentas desenhadas para o domínio, não SQL genérico.

## Opções consideradas
1. **FastMCP em Databricks App** com tools de domínio sobre as metric views
2. **MCPs gerenciados do Databricks** via Unity Gateway (Genie MCP `system.ai.genie_one_mcp` e DBSQL MCP `system.ai.dbsql`)
3. **FastMCP local** (stdio na máquina da Helena) com um token pessoal
4. **FastMCP fora do Databricks** registrado como MCP externo no Unity Gateway

## Decisão
**Opção 1.** Ela atende ao requisito do FastMCP no Databricks, mantém as tools de domínio com validação por lista fechada e reaproveita a autenticação do App.

## Prós e contras
**FastMCP em App.** 👍 Controle total das tools e do contrato de erro; autenticação do Databricks. 👎 **Não passa pelo Unity Gateway** (limitação da plataforma): rate limit e auditoria ficam por conta do App (logs estruturados); consome 1 dos 3 slots de App.
**MCPs gerenciados.** 👍 Governados pelo Unity Gateway, zero código. 👎 O DBSQL MCP permite SQL amplo (fere o menor privilégio); não mostra engenharia própria; não usa FastMCP. **Fica documentado como alternativa de uso** no README.
**Local stdio.** 👍 Simples. 👎 Token pessoal na máquina; não está "dentro do Databricks"; cada usuário instala.
**Fora do Databricks como externo.** 👍 Ganharia a governança do gateway. 👎 Exige hospedagem externa e conexão UC com credencial; complexidade e custo fora do escopo.

## Consequências
- **Positivas:** o MCP é testável com o mesmo golden set do agente (SPEC-006 §7).
- **Negativas aceitas:** sem rate limit nem auditoria **centralizados** no gateway; compensados no App (emenda abaixo). Continuam valendo a validação de entrada, o limite de 500 linhas e o warehouse 2X-Small como teto natural. Fica sem equivalente: teto de gasto e política única com o agente. A autenticação de clientes externos depende do Spike S0.5.
- **Não se aplica ao MCP:** os controles de LLM do gateway (tokens, guardrail de PII na saída), porque o MCP não chama LLM; quem raciocina é o cliente.
- **Revisitar se:** o Unity Gateway passar a aceitar registro de Apps como MCP Service. Nesse caso, migrar e herdar rate limit e auditoria.

## Emenda 2026-11-11: observabilidade e controle sem o gateway

**Contexto:** a doc *Register an MCP service* (Limitations) confirma que um MCP em Databricks Apps não pode ser registrado no Unity Gateway. O mantenedor pediu observabilidade e controles próximos dos do agente.

**Opções consideradas:**
1. **No próprio App:** span MLflow manual por tool (só atributos), auditoria por `system.query.history` com `request_id` no SQL, limitador em memória de 30 chamadas/min por usuário
2. **Limitador persistente** em tabela Delta ou Lakebase, compartilhado entre instâncias
3. **Só o que a plataforma já dá:** query history do warehouse e logs do App, sem rate limit

**Decisão:** opção 1, detalhada na SPEC-006 §6.

**Prós e contras:**
- **No App:** 👍 sem infraestrutura nova; mesmo experiment, padrão de trace tables e AI/BI do agente; o `request_id` liga trace e query. 👎 O limite zera num restart e vale por instância.
- **Limitador persistente:** 👍 sobrevive a restart. 👎 Uma escrita por chamada; o service principal precisaria de escrita fora de `atlas.semantic`, o que fere o menor privilégio. Com uma instância só na Free Edition, o ganho é pequeno.
- **Só a plataforma:** 👍 zero código. 👎 Sem rate limit; sem o usuário real no plano B (service principal); sem painel por tool.

**Revisitar se:** o App tiver mais de uma instância, ou o gateway aceitar Apps como MCP Service (aí migrar e remover a opção 1).

## Validação (Spike S0.5, 2026-11-12)
Um cliente externo (Claude Code, `claude mcp add --transport http`) chamou um App FastMCP com sucesso, e uma query disparada pela tool apareceu em `system.query.history` com `executed_by` igual ao usuário (on-behalf-of-user). O plano B (proxy `mcp-remote`, auditoria só no trace) não foi acionado. Detalhes em [S0-results](../spikes/S0-results.md). Escopo: o spike usou o template com a identidade do usuário; o fluxo OAuth interativo nativo do cliente, a renovação da credencial e vários usuários seguem como validação da P11.4/P11.5 e do S0.6.
