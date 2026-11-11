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
- **Negativas aceitas:** sem rate limit nem auditoria **centralizados** no gateway. Compensação no próprio App (SPEC-006 §6, decidido em 2026-11-11): MLflow traces por tool, auditoria por `system.query.history` (com on-behalf-of-user, o usuário real), limitador de 30 chamadas/min por usuário e página "Uso do MCP" no AI/BI. Continuam valendo a validação de entrada, o limite de 500 linhas e o warehouse 2X-Small como teto natural. O que fica sem equivalente: teto de gasto e política única com o agente. A autenticação de clientes externos depende do Spike S0.5.
- **Não se aplica ao MCP:** os controles de LLM do gateway (tokens, guardrail de PII na saída), porque o MCP não chama LLM; quem raciocina é o cliente.
- **Revisitar se:** o Unity Gateway passar a aceitar registro de Apps como MCP Service. Nesse caso, migrar e herdar rate limit e auditoria.
