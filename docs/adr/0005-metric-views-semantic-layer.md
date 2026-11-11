# ADR-0005 — Usar metric views do UC como camada semântica única

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-004, SPEC-005, SPEC-006, SPEC-007

## Contexto
A dor central da Helena: "cada área calcula a receita de um jeito". Cinco consumidores (AI/BI, Genie, agente, MCP e React) precisam devolver **o mesmo número**. Para o agente, a definição da métrica também é o principal guardrail contra alucinação.

## Critérios de decisão
- Uma definição por métrica, consumível via SQL por todos.
- Metadados (descrições, sinônimos, formatos) legíveis pelo Genie e pelo agente.
- Governada pelo UC (permissão e linhagem).

## Opções consideradas
1. **Metric views do UC** (YAML `WITH METRICS`)
2. **Views SQL comuns no gold** com a fórmula embutida
3. **dbt Semantic Layer (MetricFlow)**
4. **Métricas definidas em cada consumidor** (no código do React, nos prompts do agente)

## Decisão
**Metric views.** São nativas do UC, o Genie e o AI/BI as consomem diretamente, os sinônimos e descrições alimentam o agente, e `MEASURE()` garante a mesma agregação qualquer que seja o agrupamento.

## Prós e contras
**Metric views.** 👍 Medidas compostas (`avg_ticket` = receita / recargas) corretas em qualquer granularidade; linhagem até o gold. 👎 Recurso recente: a sintaxe evolui, há menos material na comunidade e existe risco de limitação na Free Edition (Spike S0.4).
**Views SQL.** 👍 Simples e universais. 👎 Uma view por granularidade; média de médias errada; nenhum metadado semântico para o Genie.
**dbt Semantic Layer.** 👍 Maduro e portável. 👎 Exige dbt Cloud para a API semântica; não integra com Genie e AI/BI; mais uma ferramenta.
**Métricas em cada consumidor.** 👍 Zero setup. 👎 Exatamente o problema que o produto resolve.

## Consequências
- **Positivas:** o teste de consistência entre consumidores (PRD §4) fica possível; um único `GRANT` em `semantic`.
- **Negativas aceitas:** toda nova métrica exige um PR no YAML, o que é mais lento, mas é uma decisão de governança. O MoM fica fora das medidas no MVP (SPEC-004 §5).
- **Plano B (S0.4 falhar):** views SQL por granularidade com `COMMENT` detalhado, Genie sobre o gold e o golden set ampliado.
