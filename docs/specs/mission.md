# Mission — Atlas Recarga

> Constituição do projeto, parte 1 de 3 · [mission](mission.md) · [tech-stack](tech-stack.md) · [roadmap](roadmap.md)
> Este arquivo muda raramente. Uma mudança aqui exige PR com justificativa e, se afetar uma decisão, um ADR.

## Missão
O **Atlas Recarga** dá à Diretoria Comercial da **Eaí? Telecom** uma visão **confiável, D-1 e geográfica** da rede de recarga pré-paga, **fecha a comissão de canal com revisão humana e trilha de auditoria** e responde a perguntas de negócio em linguagem natural com **números rastreáveis até a sua definição**.

Existimos para que a Helena descubra uma queda regional no dia seguinte, e não 9 dias depois, e para que nenhum real de comissão seja pago sem que duas pessoas tenham conferido.

## Para quem

| Persona | O que precisa de nós |
|---|---|
| **Helena Duarte**, Diretora Comercial | Ver onde a receita está forte ou fraca e perguntar sem depender do BI |
| **Analista de Comissões** | Fechar o mês em menos de 1h, com as divergências na frente, não numa planilha de 40 abas |
| **Gerentes Regionais** | Acompanhar a própria região até o nível de município |

Contexto completo: [discovery](../discovery.md) · Escopo e métricas: [PRD](../prd.md)

## Princípios inegociáveis

Toda spec, todo PR e todo agente (de produto ou de código) respeitam estes princípios. Um conflito entre um princípio e uma spec se resolve **a favor do princípio**, e a spec é corrigida.

1. **Uma métrica, uma definição.** Toda métrica de negócio vive em `atlas.semantic`. Nenhum consumidor (dashboard, agente, MCP ou app) recalcula uma métrica por conta própria nem lê `gold`, `silver` ou `bronze`. → ADR-0005
2. **A IA nunca escreve, aprova nem paga.** O agente de negócio e o MCP são somente leitura. Nenhuma IA participa do cálculo ou da aprovação de comissão. → ADR-0010
3. **Sem número sem fonte.** Toda resposta numérica do agente ou do MCP cita a metric view, as medidas, os filtros e o período. Um número sem tool call na mesma conversa é bug. → SPEC-005
4. **O irreversível exige duas pessoas.** A transição que equivale a pagamento exige duas aprovações humanas de atores distintos, e o resultado é imutável (append-only). A correção é sempre um novo lote. → ADR-0010
5. **Dados 100% sintéticos, zero efeito externo.** Nenhum dado real ou pessoal; nenhum pagamento, envio ou documento com validade sai do workspace. → ADR-0011
6. **Spec antes de código.** Nenhuma implementação sem uma spec aprovada que a descreva. Se o código precisa adivinhar, a spec está incompleta e é corrigida primeiro.
7. **Toda decisão tem alternativas registradas.** Uma escolha que afeta a arquitetura, a segurança ou o custo vira um ADR com pelo menos 2 alternativas descartadas.
8. **A qualidade é medida, não declarada.** A acurácia do agente, a reconciliação da comissão e o frescor dos dados têm metas numéricas verificadas automaticamente. Regressão bloqueia o merge. → SPEC-008
9. **Os limites do agente de código são aplicados pela ferramenta.** O que é proibido ao agente de código é bloqueado por hook ou permissão, não apenas pedido em texto. → ADR-0012

## Fora da missão
- Substituir o sistema de pagamento ou o ERP da operadora.
- Tomar decisões comerciais automaticamente (bloquear PDV, mudar meta, aprovar pagamento).
- Ser uma plataforma genérica de BI para outras áreas além da comercial de pré-pago.
- Prever o futuro no MVP (o forecast é v2, depois de haver histórico e backtesting).
