# ADR-0010 — Fechar a comissão com cálculo determinístico, 2 aprovações humanas e lote imutável

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-003, SPEC-005

## Contexto
O pagamento de comissão é **a etapa irreversível do produto**. Pagamento feito não volta. Em março (no case), R$ 212 mil foram pagos a mais por uma fórmula de planilha errada e a recuperação levou 4 meses. A pergunta do desafio: "o que é irreversível, e quem deveria aprovar antes?".

## Critérios de decisão
- Erro de cálculo detectado **antes** de qualquer humano aprovar.
- Aprovação com responsabilidade individual e trilha de auditoria.
- Impossível alterar o que já foi "pago".
- IA fora da decisão.

## Opções consideradas
1. **Cálculo determinístico + reconciliação dupla + 2 aprovações humanas com segregação + lote append-only**
2. **Cálculo automático com uma aprovação** (Helena confere o total)
3. **IA sugere aprovar ou rejeitar o lote** e o humano confirma
4. **Totalmente automático** quando a reconciliação passa

## Decisão
**Opção 1.** A reconciliação por duas implementações independentes pega o erro de fórmula; a analista confere as linhas com flag; a diretora dá o aval com um ator diferente; o lock copia para uma tabela `delta.appendOnly` e a correção só acontece via lote de ajuste.

## Prós e contras
**Opção 1.** 👍 Defesa em profundidade; auditoria completa em `batch_events`; o erro de março seria pego na reconciliação. 👎 O fechamento depende de duas pessoas disponíveis; há dois códigos de cálculo para manter.
**Uma aprovação.** 👍 Mais rápido. 👎 É o processo atual que falhou: ninguém confere linha a linha.
**IA sugere.** 👍 Poderia priorizar a revisão. 👎 Viés de automação: o humano tende a carimbar a sugestão. É exatamente o medo da Helena ("não quero IA mexendo em comissão").
**Automático.** 👍 Zero esforço. 👎 Uma reconciliação que passa não pega regra de negócio errada (faixa mal configurada passa nas duas implementações se ambas leem a mesma tabela de faixas).

## Consequências
- **Positivas:** a métrica "100% dos lotes com 2 aprovadores distintos" é auditável por SQL.
- **Negativas aceitas:** o fechamento leva até 1h (e não minutos) por causa da revisão humana; é o custo da segurança. As faixas ficam **hardcoded e versionadas no código**, e mudança de faixa exige PR com revisão obrigatória (CODEOWNERS).
- **Na Free Edition:** o S0.6 (2026-11-12) confirmou que um segundo usuário entra e pode ser adicionado a grupos `atlas_*` criados por nós, então as 2 aprovações podem usar identidades distintas (a confirmação final depende dos grupos `atlas_commission_*`, na P5.2). `ALLOW_SAME_APPROVER_DEMO` fica só como contingência explícita, auditada e marcada no lote. Nunca é o padrão.
- **Fronteira para agentes:** nenhum agente (de produto ou de código) executa `atlas_commission_review`. Ver ADR-0012.
- **Revisitar se:** surgir uma UI de aprovação (v2) ou o volume de lotes justificar aprovação por amostragem.
