# ADR-0003 — Organizar o catálogo `atlas` em medalhão + schemas de propósito

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-002, SPEC-004

## Contexto
Os dados servem a públicos com permissões muito diferentes: pipeline, analista de comissões, diretoria, agente de IA, MCP e app. A organização no UC define o que cada um pode ver.

## Critérios de decisão
- Menor privilégio fácil de expressar com `GRANT` por schema.
- Fonte de verdade da comissão isolada de qualquer leitor.
- Nomes previsíveis para pessoas e para o agente de código.

## Opções consideradas
1. **Um catálogo com schemas por camada e propósito:** `raw, bronze, silver, gold, semantic, commission, eval, observability`
2. **Um catálogo por camada** (`atlas_bronze`, `atlas_silver`, …)
3. **Um schema único** com prefixos de tabela (`brz_`, `slv_`, `gld_`)

## Decisão
**Opção 1.** A permissão de leitura de negócio vira um só `GRANT SELECT ON SCHEMA atlas.semantic`, e `commission` fica isolado de todos os consumidores.

## Prós e contras
**Opção 1.** 👍 Grants simples; a linhagem é lida em ordem; cabe na Free Edition. 👎 Uma separação por ambiente (dev/prod) exigiria um prefixo de catálogo.
**Catálogo por camada.** 👍 Isolamento forte. 👎 Excesso de objetos para um MVP; joins entre catálogos poluem o código.
**Schema único.** 👍 Simples. 👎 Impossível dar um privilégio mínimo limpo; o agente veria tudo.

## Consequências
- **Positivas:** "consumidores só leem `semantic`" é uma regra verificável por teste (SPEC-004 §8).
- **Negativas aceitas:** sem separação dev/prod no MVP; o target `dev` do bundle usa o catálogo `atlas_dev`.
- **Revisitar se:** houver múltiplos ambientes reais ou RLS por região (v3).
