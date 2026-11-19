# ADR-0013 — Avaliar e monitorar o agente com MLflow 3 GenAI (offline + gate + produção)

- **Status:** aceito (Spike S0.3 passou em 2026-11-12; plano B também validado) · **Data:** 2026-11-11 · **Relacionados:** SPEC-005, SPEC-008, ADR-0006

## Contexto
A H4 do discovery exige que o agente seja confiável **e continue confiável**. Mudanças de prompt, de modelo (`ATLAS_LLM_SERVICE`) ou de metric view podem degradar a qualidade em silêncio. O medo da Helena é levar um número errado ao comitê. Uma avaliação única no lançamento não protege contra isso.

## Critérios de decisão
- Mesmos scorers no desenvolvimento, no CI e na produção (resultados comparáveis).
- Integração com os traces que o agente já gera (SPEC-005 §5).
- Custo de LLM-judge controlado (cota da Free Edition).
- Golden set que não quebra quando os dados sintéticos são regerados.

## Opções consideradas
1. **MLflow 3 GenAI:** `mlflow.genai.evaluate` + dataset de avaliação no UC + scorers de código e LLM judges + production monitoring (Beta)
2. **Só avaliação offline** antes de cada release, sem monitoramento
3. **Avaliação manual** periódica (uma pessoa testa 30 perguntas)
4. **Framework externo** (Ragas ou DeepEval) rodando no CI

## Decisão
**Opção 1**, em três camadas (offline, gate de PR, produção). A estratégia de custo: scorers determinísticos de código em 100% dos traces e LLM judges só numa amostra de 20%. O golden set guarda a **SQL de referência**, não o valor.

## Prós e contras
**MLflow 3.** 👍 Nativo dos traces que já existem; o feedback fica anexado ao próprio trace; dataset versionado no UC; o mesmo scorer em todo lugar. 👎 Production monitoring em Beta (não funcionou na P10.8: o plano B é o caminho); a API ainda evolui.
**Só offline.** 👍 Barato. 👎 Não detecta a degradação real nem perguntas novas fora do golden set.
**Manual.** 👍 Julgamento humano rico. 👎 Não escala, não bloqueia PR, depende de disciplina.
**Externo.** 👍 Métricas prontas e portáveis. 👎 Duplica a infraestrutura de traces; os resultados ficam fora do UC; não integra com o monitoramento do Databricks.

## Consequências
- **Positivas:** a métrica de acurácia do PRD vira um **gate de merge**; as falhas de produção alimentam o golden set (ciclo de melhoria).
- **Negativas aceitas:** o gate custa ~30 chamadas ao agente por PR relevante e precisa de um token do workspace como GitHub secret (escopo mínimo). O scorer `numeric_match` depende de extrair o número principal da resposta, por isso o formato do bloco `Fonte:` é contrato (SPEC-005 §4).
- **Spike S0.3 (2026-11-12):** um scorer de código agendado (`start()`) anexou feedback `CODE` a traces novos, sem `evaluate`, e o plano B abaixo também foi validado. **Não validado no S0.3:** LLM judge em amostra de 20%, latência trace→feedback e persistência do scorer após `stop()`/redeploy; reconfirmar na P10.8. Ver `docs/spikes/S0-results.md`.
- **P10.8 (2026-11-17): o Beta não funcionou.** Os 3 LLM judges foram registrados com `start()` a 20% no experiment `atlas_agent_traces` (que tem trace location no UC) e nenhum dos 20 traces criados depois ganhou assessment. A causa (atraso ou limitação do Beta) não foi isolada. Efeito: o plano B é o caminho em uso, e o `eval/start_monitoring.py` é só uma tentativa opcional. **P12.9 (2026-11-19): reconfirmado, o Beta segue sem efeito.** Depois de 40 perguntas novas ao App (39 com HTTP 200), o experiment tinha 61 traces e 0 com assessment, em quatro contagens seguidas; o plano B continua em uso. Reconfirmar se o production monitoring virar GA.
- **Plano B (S0.3, em uso):** job diário com `mlflow.search_traces` gravando em `atlas.observability.agent_quality_scores` (SPEC-008 §6, P10.8); `agent_quality_daily` é uma view sobre essa tabela. O painel e a fila precisam de tabelas, então o job roda de qualquer forma; no `dev` ele pontuou 20 traces reais, com os scorers de código em 100% e os judges em ~20%.
- **Revisitar se:** o production monitoring virar GA, ou o custo dos judges passar da cota (reduzir a amostra para 10%).
