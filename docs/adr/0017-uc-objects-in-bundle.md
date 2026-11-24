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

**Verificação (2026-11-24, CLI 1.24.0):** a condição falhou como escrita. No `mode: development` os schemas saem como `dev_<usuário>_<nome>`; o Volume e os `grants` não são prefixados; `presets.name_prefix: ""` é ignorado e não há preset só para schemas. Revisão da decisão: o target `dev` **deixa de usar `mode: development`** e declara os presets que importam (`pipelines_development: true`, `trigger_pause_status: PAUSED`). Com isso schemas, jobs e pipeline do `dev` saem sem prefixo, os nomes fixos (ADR-0003) se mantêm e o bundle declara os schemas já existentes. O `demo` segue em `mode: production`. Alternativas descartadas nesta revisão: (a) manter os schemas no script (a demo continua com um passo manual); (b) trocar as referências por nomes prefixados ou variáveis (mexe em pipeline, metric views, apps e scripts, e em dados existentes).

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
- **Negativas, aceitas conscientemente:** o `dev` perde o prefixo por usuário e as tags automáticas do `mode: development` (há um só usuário) e os jobs do `dev` mudam de nome (`[dev <usuário>] atlas_daily` vira `atlas_daily`); a migração mexe em objetos já existentes no `dev`; o bundle precisa assumir (bind) schemas criados pelo script, e isso deve ser testado antes do `demo`.
- **Plano B / gatilho para revisitar:** o `validate` mostrar nomes prefixados, a CLI não suportar `grants` em algum recurso, ou o catálogo poder ser declarado (então sai do script de bootstrap).

## Passos da P13.0
A Fase 13 não tem spec nem `tasks.md` (o teste de higiene isenta fases sem spec); os passos ficam aqui.
1. `docs(specs)` anterior ao código: esta revisão do ADR.
2. `databricks.yml`: trocar `mode: development` do `dev` pelos `presets` (`pipelines_development: true`, `trigger_pause_status: PAUSED`); declarar os 8 schemas, o Volume `raw.landing` (com `COMMENT`) e os `grants` de `atlas_readers` (`USE CATALOG`; `USE SCHEMA`, `SELECT` e `EXECUTE` em `semantic`); a lista de leitores (ADR-0016) vira variável do bundle.
3. `scripts/setup_workspace.py`: manter só catálogo, grupos e membros; ajustar `tests/test_setup_workspace.py`.
4. Conferir o que dependia do prefixo `[dev <usuário>]` (`check_atlas_daily.py`, `check_genie_space.py`, docs); `bundle validate -t dev` e `-t demo` passam.
5. Mantenedor: `bundle deploy -t dev` assumindo (bind) schemas e Volume já existentes, depois `check_readers_permissions.py`; por fim um deploy num catálogo vazio.
