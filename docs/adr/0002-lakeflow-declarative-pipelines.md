# ADR-0002 — Usar Lakeflow Spark Declarative Pipelines para o medalhão

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-002

## Contexto
Precisamos de bronze → silver → gold incremental, com regras de qualidade explícitas, linhagem e reprocessamento simples, dentro de **1 pipeline ativo por tipo** na Free Edition.

## Critérios de decisão
- Qualidade declarada junto da tabela, auditável.
- Incrementalidade sem controle manual de checkpoints.
- Linhagem automática no UC.
- Pouco código de orquestração.

## Opções consideradas
1. **Lakeflow Spark Declarative Pipelines (`pyspark.pipelines`)**, um pipeline serverless
2. **Notebooks PySpark + Jobs** com `MERGE` e checkpoints manuais
3. **dbt (dbt-databricks)** com testes dbt

## Decisão
**Lakeflow SDP.** Expectations (`expect`, `expect_or_drop`, `expect_or_fail`) dão uma política de qualidade por linha declarada no código; streaming tables e materialized views resolvem a incrementalidade; a linhagem é nativa.

## Prós e contras
**SDP.** 👍 Qualidade e métricas de expectations prontas; full refresh trivial. 👎 Menos flexível para lógica imperativa e com estado; a cota de 1 pipeline força todas as camadas num só grafo.
**Notebooks + Jobs.** 👍 Flexibilidade total. 👎 Checkpoints, deduplicação e qualidade feitos à mão; mais código para errar.
**dbt.** 👍 Testes e documentação maduros, conhecido no mercado. 👎 Mais uma ferramenta; ingestão incremental de arquivos fica fora do dbt; duplica a camada semântica com as metric views (ADR-0005).

## Consequências
- **Positivas:** as regras de qualidade da SPEC-002 viram código revisável no PR.
- **Negativas aceitas:** o **fechamento de comissão fica fora do pipeline** (é um job), porque uma máquina de estados com aprovação humana não combina com um grafo declarativo reprocessável. Um único pipeline concentra todas as camadas.
- **Revisitar se:** a cota permitir múltiplos pipelines, ou a lógica do silver precisar de estado complexo.
