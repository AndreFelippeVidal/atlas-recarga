# ADR-0004 — Geolocalizar por código IBGE + malha GeoJSON (CEP híbrido depois)

- **Status:** aceito · **Data:** 2026-11-11 · **Relacionados:** SPEC-001, SPEC-007

## Contexto
O mapa precisa agregar recargas por UF e por município. A ideia inicial era gerar CEPs sintéticos e geocodificá-los numa API gratuita.

## Critérios de decisão
- Pipeline determinístico e sem dependência externa em tempo de execução.
- Match de 100% entre os dados e a geometria do mapa.
- Respeito a rate limits e termos de uso de APIs públicas.

## Opções consideradas
1. **Código IBGE do município gerado direto nos dados sintéticos + malha do IBGE versionada no repo**
2. **CEP sintético + API gratuita (ViaCEP, BrasilAPI) chamada no pipeline**
3. **Híbrido:** CEP sintético resolvido para código IBGE **uma única vez**, numa tabela de referência cacheada no UC

## Decisão
**Opção 1 no MVP; Opção 3 na v1.1.** O mapa coroplético precisa de município, não de coordenada. O código IBGE é a chave natural da malha oficial.

## Prós e contras
**IBGE + GeoJSON.** 👍 Zero chamadas externas; match exato pelo código; build reproduzível. 👎 Menos "realista": não há endereço nem ponto por PDV.
**CEP + API no pipeline.** 👍 Parece mais real. 👎 2M de chamadas violam o uso justo de APIs gratuitas; latência; o pipeline falha se a API cair; CEPs sintéticos muitas vezes não existem e não resolvem.
**Híbrido.** 👍 Realismo de endereço sem acoplamento em runtime (consulta uma vez, cacheia). 👎 Mais trabalho; ainda depende de API externa na carga inicial da referência.

## Consequências
- **Positivas:** o teste "100% dos municípios da malha têm match" (SPEC-007) é trivial e confiável.
- **Negativas aceitas:** sem mapa de pontos por PDV no MVP. A geometria simplificada perde detalhe de fronteira (aceitável para coroplético).
- **Revisitar:** na v1.1, implementar o híbrido. O gatilho é a necessidade de visualização por PDV ou de raio de atendimento.
