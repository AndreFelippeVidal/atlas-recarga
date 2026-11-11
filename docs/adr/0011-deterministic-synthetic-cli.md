# ADR-0011 — Gerar os dados sintéticos com um CLI determinístico e cenários injetados

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-001, SPEC-008

## Contexto
Restrição do desafio: nada de dado real ou sensível. Os dados precisam ser realistas o bastante para o mapa contar uma história e para o agente ter perguntas interessantes, e precisam conter **defeitos conhecidos** para testar qualidade, comissão e avaliação.

## Critérios de decisão
- Reprodutibilidade (testes e golden set estáveis).
- Verdade-base conhecida para cada anomalia.
- Escala configurável dentro das cotas da Free Edition.

## Opções consideradas
1. **CLI próprio (`atlas-cli`) com seed, distribuições calibradas e cenários nomeados**
2. **Dataset estático** gerado uma vez e versionado no repo
3. **Gerador genérico** (Faker ou dbldatagen) sem cenários de negócio
4. **Dataset público adaptado** (por exemplo, dados abertos da Anatel)

## Decisão
**Opção 1.** O `_manifest.json` com as contagens exatas de cada anomalia vira o oráculo dos testes do pipeline e da comissão.

## Prós e contras
**CLI próprio.** 👍 Determinístico; cenários de negócio (queda no PA, fracionamento); carga incremental diária simulada. 👎 Esforço de calibrar as distribuições.
**Estático.** 👍 Simples. 👎 Arquivos de centenas de MB no git; não simula a carga D-1; mudar um cenário exige regerar tudo e commitar.
**Gerador genérico.** 👍 Rápido. 👎 Dados sem história: o mapa fica uniforme e o agente não tem nada a descobrir.
**Dataset público.** 👍 Realismo. 👎 Agregado demais (sem transações nem PDVs); risco de interpretarem os resultados como fatos reais.

## Consequências
- **Positivas:** o golden set (SPEC-008) guarda SQL, e os números esperados são recalculados sobre qualquer seed.
- **Negativas aceitas:** o realismo é tão bom quanto a calibração. As distribuições ficam documentadas na SPEC-001 e podem ser ajustadas por PR.
- **Revisitar se:** surgir um dataset sintético público de telecom adequado, ou for preciso volume acima de 10M (geração distribuída no próprio Databricks).
