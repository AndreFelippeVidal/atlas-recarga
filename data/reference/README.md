# data/reference

Dados **públicos** versionados (referência de municípios do IBGE). Nunca dados reais de pessoas ou empresas.

## municipalities_ibge.csv

5.570 municípios, gerados uma vez por `scripts/build_reference.py` (nunca em runtime). Colunas: `municipality_ibge_code` (7 dígitos, string), `municipality_name`, `uf`, `region`, `population`, `ddd`.

- **Fontes:** API de Localidades do IBGE (município, UF, região) e Censo 2022 do IBGE via SIDRA, tabela 4709 (população).
- **`ddd` é aproximado:** não existe fonte pública por município nas bases usadas, então cada município recebe o DDD da sua região imediata do IBGE, a partir de uma tabela mantida à mão no script. Municípios de fronteira entre áreas podem ficar com o DDD vizinho. Serve para dados sintéticos e para separar o mapa por DDD; não é referência de telecom.
- **Boa Esperança do Norte (MT)** fica de fora: a API do IBGE lista 5.571 unidades, mas o Censo 2022 tem população de 5.570.
- Para regenerar: `uv run python scripts/build_reference.py` e commitar o CSV.
