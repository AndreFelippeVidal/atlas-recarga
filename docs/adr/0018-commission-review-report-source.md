# ADR-0018 — O relatório de revisão da comissão lê `commission.*`, não a camada semântica

- **Status:** proposto
- **Data:** 2026-11-16
- **Decisores:** mantenedor
- **Relacionados:** SPEC-003 §5.4, SPEC-004 §4 e §7, ADR-0005, ADR-0010, ADR-0016

## Contexto
A analista e a diretora precisam ver o rascunho **antes** de aprovar: totais, top 20, flags e a comparação com o mês anterior (SPEC-003 §5.4). Um rascunho nunca aparece na camada semântica (SPEC-004 §4: `mv_commission` só tem lotes `locked`), e `atlas_readers` não recebe nada em `commission` (SPEC-004 §7). O princípio 1 e a lista Proibido do `tech-stack.md` dizem que um consumidor só lê `atlas.semantic`. O relatório de revisão precisa ler exatamente o que a camada semântica não pode mostrar.

## Critérios de decisão
- Ver o lote em revisão antes do lock, sem enfraquecer o princípio 1 para os consumidores (agente, MCP, apps, Genie).
- Uma só definição de cada número: o relatório não recalcula comissão, só exibe o que `batch_lines` já tem.
- Menor privilégio: `atlas_readers` continua sem acesso a `commission`.
- Funciona na Free Edition e cabe na P8.8.

## Opções consideradas
1. **Relatório do próprio domínio de comissão:** dashboard e notebook leem `commission.*` (somente leitura), fora do conjunto de consumidores do princípio 1.
2. **Esperar a `mv_commission` (P8.11):** só cobre lotes `locked`; a revisão acontece com o lote em `under_review`, então não serve.
3. **Expor o rascunho numa metric view de revisão em `semantic`:** quebra a regra "rascunho nunca na camada semântica" e abriria `draft` a `atlas_readers` e ao Genie.

> Regra deste repositório: um ADR com menos de 2 alternativas descartadas não é aceito no review.

## Decisão
**Opção 1.** O relatório `commission_review` é parte do domínio de comissão, não um consumidor da camada semântica. Regras: lê só `commission.*`, somente leitura e sem SQL livre (consultas fixas em `commission/review_sql/`, parâmetro vinculado no notebook); nenhum agente, MCP, app ou Genie o usa; `atlas_readers` não ganha acesso; vale só para o fluxo de revisão da SPEC-003. Quem vê os dados é a identidade que publica o dashboard, e o notebook roda com as permissões de quem o abre (os grupos `atlas_commission_*` são de workspace e não valem como grant no UC, ADR-0016).

## Prós e contras das opções
### 1. Relatório do domínio
- 👍 Mostra o rascunho a quem aprova; nenhum cálculo novo; o princípio 1 segue valendo para os consumidores.
- 👎 Abre uma exceção nominal à leitura de `commission`; a restrição de acesso depende de quem publica o dashboard.
### 2. Esperar a `mv_commission`
- 👍 Nenhuma exceção.
- 👎 Não cobre o lote em revisão. Descartada.
### 3. Metric view de revisão
- 👍 Uma porta só.
- 👎 Expõe rascunho a leitores e ao Genie, contra a SPEC-004 §4. Descartada.

## Consequências
- **Positivas:** a analista revisa com os números do lote; a regra de leitura continua simples de testar (os consumidores não leem `commission`).
- **Negativas, aceitas conscientemente:** a exceção precisa ser lembrada nas revisões; o dashboard depende da identidade do publicador.
- **Plano B / gatilho para revisitar:** se a UI de aprovação (v2) ou uma metric view de revisão com RLS passar a existir, migrar o relatório e remover a exceção; se um consumidor pedir acesso ao relatório, reabrir.
