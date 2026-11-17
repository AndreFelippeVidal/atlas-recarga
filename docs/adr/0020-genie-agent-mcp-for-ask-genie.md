# ADR-0020 — `ask_genie` usa o Genie Agent MCP, restrito ao Space

- **Status:** proposto
- **Data:** 2026-11-16
- **Decisores:** mantenedor
- **Relacionados:** SPEC-005 §3 e §5, ADR-0006, ADR-0007, ADR-0016

## Contexto
O `ask_genie` precisa de NL→SQL sobre as metric views. A SPEC-005 §3 o restringe ao Space `Atlas Recarga` (lista fechada, só `semantic`), e o §5 esperava vê-lo como `MCP_SERVICE` na `usage` do Unity Gateway. Pela documentação do Databricks os dois não cabem num servidor só: o Genie One MCP passa pelo Gateway mas responde sobre o workspace inteiro; o Genie Agent MCP fica restrito a um Space mas não passa pelo Gateway.

## Critérios de decisão
- Escopo restrito ao Space (princípio da lista fechada).
- Governança e observabilidade da chamada.
- Maturidade do endpoint.

## Opções consideradas
1. **Genie Agent MCP** (`/api/2.0/mcp/genie/{space_id}`)
2. **Genie One MCP** (`system.ai.genie_one_mcp`, via Unity Gateway)
3. **Genie Conversation API pelo SDK**, sem MCP

## Decisão
**Opção 1.** O escopo restrito ao Space pesa mais que o `MCP_SERVICE` na `usage`.

## Prós e contras
**Genie Agent MCP.** 👍 Só o Space `Atlas Recarga`; `CAN RUN` + `SELECT` em `semantic` limitam o acesso. 👎 Não passa pelo Gateway (sem `usage`, grants de MCP, policies); Public Preview; exige o preview *Managed MCP Servers*.
**Genie One MCP.** 👍 Governado pelo Gateway, aparece como `MCP_SERVICE`. 👎 Busca no workspace inteiro; a única barreira seriam os grants do service principal.
**Conversation API (SDK).** 👍 Sem preview de MCP. 👎 Também fora do Gateway e mais código de polling para manter.

## Consequências
- **Positivas:** a lista fechada da SPEC-005 §3 vale para o Genie.
- **Negativas aceitas:** a observabilidade do `ask_genie` vem do span no trace MLflow, não da `usage`.
- **Revisitar se:** o Genie Agent MCP passar pelo Gateway ou o Genie One MCP aceitar escopo por Space.
