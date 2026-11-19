# ADR-0024 — Renderizar o Markdown do chat com `react-markdown` e uma lista fechada de elementos

- **Status:** aceito
- **Data:** 2026-11-19
- **Decisores:** mantenedor
- **Relacionados:** SPEC-007 §4, ADR-0023, SPEC-005 (prompt do agente)

## Contexto
O agente responde em Markdown (o `prompts/v2.md` pede `**negrito**`, listas e o bloco `Fonte:`), mas o painel de chat do `atlas-web` mostra a resposta num `<p>` de texto puro. O mantenedor viu `**outubro de 2026**` com os asteriscos literais no `dev`. O painel também é visualmente simples demais para uma demo.

Restrições: a resposta vem de um LLM, então é **entrada não confiável** (XSS); o frontend não pode calcular nem reformatar número (princípios da mission e ADR-0005); o bundle é estático e servido pelo próprio App (sem CDN em runtime).

## Critérios de decisão
- Segurança: nenhum HTML cru da resposta chega ao DOM; links só `http(s)`.
- Cobertura: negrito, itálico, listas, código, tabelas simples e links, com a resposta ainda chegando em streaming.
- Custo de manter: sem parser próprio para consertar.
- Peso no bundle (o build é versionado em `apps/web/static`).

## Opções consideradas
1. **`react-markdown` + `remark-gfm`, com `skipHtml`, lista fechada de elementos e `urlTransform` só http(s)**
2. **Renderizador próprio mínimo** (negrito, itálico, código inline, listas, parágrafos)
3. **Pedir texto puro ao agente** (tirar o Markdown do prompt)
4. **`marked` ou `markdown-it` + `DOMPurify` com `dangerouslySetInnerHTML`**

> Regra deste repositório: um ADR com menos de 2 alternativas descartadas não é aceito no review.

## Decisão
Escolhemos a **opção 1**. O `react-markdown` monta elementos React (não injeta HTML), então a superfície de XSS é pequena por construção, e a configuração acima a reduz mais. O `remark-gfm` cobre tabelas, que as respostas de comparação usam.

## Prós e contras das opções
### 1. `react-markdown` + `remark-gfm`
- 👍 Sem `dangerouslySetInnerHTML`; mantido e muito usado; plugins e `components` para o estilo.
- 👎 Duas dependências novas e algumas dezenas de KB no bundle; durante o streaming, um `**` ainda sem fechar aparece literal até o par chegar.

### 2. Renderizador próprio mínimo
- 👍 Zero dependência.
- 👎 Não cobre tabelas nem os casos de borda do Markdown; parser próprio vira superfície de bug e de XSS que o time teria de manter.

### 3. Texto puro
- 👍 Nada a renderizar.
- 👎 Resposta sem ênfase e com listas ilegíveis; muda o prompt e reabre o golden set e o gate de CI da P10.7, por um problema que é de apresentação.

### 4. `marked`/`markdown-it` + `DOMPurify`
- 👍 Muito flexível.
- 👎 Passa por `dangerouslySetInnerHTML` e depende de um sanitizador ficar certo em toda atualização; é o caminho com mais risco para o mesmo resultado.

## Consequências
- **Positivas:** a resposta aparece formatada; a segurança não depende de um sanitizador; o texto do agente continua sendo exibido sem recalcular número (a renderização só muda a forma, não os valores).
- **Negativas, aceitas conscientemente:** duas dependências novas no frontend (`pnpm audit` no CI passa a cobri-las); um marcador sem par pode aparecer por instantes no streaming.
- **Plano B / gatilho para revisitar:** se o bundle passar do orçamento de tamanho do `atlas-web` ou surgir uma vulnerabilidade sem correção na cadeia `remark`/`rehype`, trocar pela opção 2 só para o subconjunto que as respostas usam.
