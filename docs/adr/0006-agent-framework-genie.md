# ADR-0006 — Agente com Mosaic AI Agent Framework, usando Genie como ferramenta

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-005, SPEC-008

## Contexto
O objetivo final do produto é um agente que responda a perguntas de negócio com confiabilidade executiva, governado pelo Databricks, e que evolua para personas. O Genie sozinho responde bem a perguntas analíticas, mas oferece pouco controle sobre o formato, a citação, a recusa e a composição com outras ferramentas.

## Critérios de decisão
- Controle explícito sobre tools, formato de resposta e recusa.
- Tracing e avaliação nativos (MLflow 3).
- Caminho claro para personas (v2).
- Executar dentro do Databricks, com o LLM via Unity Gateway.

## Opções consideradas
1. **Agent Framework (LangGraph + `databricks-langchain`) em Databricks App, com Genie e UC functions como tools**
2. **Só o Genie Space**, exposto diretamente ou via Genie MCP gerenciado
3. **Agente custom fora do Databricks** (LangGraph em outro host, chamando a API SQL)
4. **Agent Bricks (agente declarativo gerado pela plataforma)**

## Decisão
**Opção 1.** O Genie entra como a tool de NL→SQL sobre as metric views, e o agente impõe as regras do produto: lista fechada de tools, bloco `Fonte:` obrigatório, recusa, assumir o último mês fechado.

## Prós e contras
**Agent Framework + Genie.** 👍 Combina a qualidade do Genie com controle de produto; traces por tool; personas viram configuração do grafo. 👎 Mais código para manter; duas camadas de raciocínio (agente e Genie) aumentam a latência.
**Só Genie.** 👍 Zero código, nativo. 👎 Sem citação garantida, sem recusa customizada, sem composição; personas limitadas às instruções do space.
**Custom fora do Databricks.** 👍 Liberdade total. 👎 Perde a governança do UC e do Unity Gateway, que é o objetivo principal do projeto.
**Agent Bricks.** 👍 Rápido de montar. 👎 Menos controle sobre os guardrails específicos e menos demonstrativo como trabalho de engenharia.

## Consequências
- **Positivas:** cada regra da SPEC-005 §4 vira um scorer verificável (SPEC-008).
- **Negativas aceitas:** latência maior, com orçamento de p95 de 15s. O agente depende da disponibilidade do Genie (fallback para UC functions).
- **Revisitar se:** o Genie ganhar controle nativo de citação e recusa, ou o p95 passar de 15s de forma persistente.
