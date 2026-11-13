# ADR-0017 — Declarar schemas, volume e grants do Unity Catalog no bundle

- **Status:** proposto
- **Data:** 2026-11-13
- **Decisores:** mantenedor
- **Relacionados:** ADR-0003, ADR-0016, SPEC-002 §2, SPEC-003 §3

## Contexto
Hoje `scripts/setup_workspace.py` cria o catálogo, os 8 schemas, o Volume `raw.landing` e os grupos, e concede os grants (inclusive por principal, ADR-0016). É idempotente, mas fica fora do bundle: o `bundle validate` do CI não o enxerga, o estado dos objetos não é rastreado e a demo exige um passo manual além do `bundle deploy`. A prática recomendada pela Databricks é declarar no bundle o que ele sabe declarar (schemas, volumes e `grants`), e deixar em job idempotente o que ele não declara, como as tabelas de `commission.*` (P8.2). O que não cabe no bundle é o bootstrap de uma vez só: grupos não são recurso de bundle, e na Free Edition o catálogo pode ser restrito.

Risco conhecido: no `mode: development` o bundle pode prefixar os nomes dos recursos (`dev_<usuário>_`). Schemas com nome alterado quebrariam as referências fixas (`atlas_dev.gold`, pipeline, metric views).

## Critérios de decisão
- A demo sobe com `bundle deploy`, sem passo manual de setup além do bootstrap.
- Os nomes dos schemas permanecem fixos nos dois targets (ADR-0003).
- Os grants continuam por principal e verificáveis (ADR-0016).
- Funciona na Free Edition.

## Opções consideradas
1. **Híbrido:** schemas, Volume e grants como recursos do bundle; catálogo e grupos num script de bootstrap mínimo.
2. **Tudo em script** (o estado atual): `setup_workspace.py` cria e concede tudo.
3. **Tudo em job do bundle:** um job idempotente executa o mesmo SQL do script.

> Regra deste repositório: um ADR com menos de 2 alternativas descartadas não é aceito no review.

## Decisão
**Opção 1**, condicionada a uma verificação na task P13.0: `databricks bundle validate` deve mostrar os schemas com o nome fixo no target `dev`. Se o prefixo de desenvolvimento alterar os nomes e não houver como desligá-lo só para schemas, os schemas voltam ao script e este ADR é revisto. A lista de leitores (ADR-0016) passa a ser uma variável do bundle.

## Prós e contras das opções
### 1. Híbrido
- 👍 Estado rastreado, deriva visível, validado no CI, e a demo depende de um único `bundle deploy`.
- 👎 Dois lugares para ler (bundle e bootstrap); depende do suporte da CLI a cada recurso.
### 2. Tudo em script
- 👍 Já funciona e está testado.
- 👎 Fora do CI e sem estado; a demo exige um passo manual; o script mantém lista própria de schemas e catálogos, duplicada do `databricks.yml`.
### 3. Tudo em job
- 👍 Roda dentro do bundle e do workspace.
- 👎 Continua imperativo, sem estado nem detecção de deriva; um grant removido à mão só reaparece quando o job rodar.

## Consequências
- **Positivas:** uma só fonte para schemas e grants; o `demo` reproduzível a partir do README.
- **Negativas, aceitas conscientemente:** a migração mexe em objetos já existentes no `dev`; o bundle precisa assumir (bind) schemas criados pelo script, e isso deve ser testado antes do `demo`.
- **Plano B / gatilho para revisitar:** o `validate` mostrar nomes prefixados, a CLI não suportar `grants` em algum recurso, ou o catálogo poder ser declarado (então sai do script de bootstrap).
