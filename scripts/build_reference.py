"""Build `data/reference/municipalities_ibge.csv` (SPEC-001 §4, task P4.2).

Run **once** by the maintainer; the generated CSV is committed. Never runs at
runtime (the CLI reads only the committed CSV).

    uv run python scripts/build_reference.py

Public sources:
- Municipalities, UF and region: IBGE Localidades API v1
  https://servicodados.ibge.gov.br/api/v1/localidades/municipios
- Population: IBGE Censo 2022, SIDRA table 4709, variable 93 (resident population)
  https://apisidra.ibge.gov.br/values/t/4709/n6/all/v/93/p/2022
- DDD: **approximation** by IBGE "região imediata". Neither IBGE nor the sources
  used here publish a DDD per municipality, so each municipality gets the DDD of
  its região imediata, from a hand-kept table (DDD_BY_REGION below) on top of a
  default per UF. Border municipalities can end up with the neighbouring DDD.
  Good enough for synthetic data and for splitting the map by DDD; do not use it
  as a telecom reference.

Municipalities without a Censo 2022 population (IBGE lists 5,571 units, SIDRA has
5,570) are left out, so the file has exactly 5,570 rows.
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

MUNICIPALITIES_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
POPULATION_URL = "https://apisidra.ibge.gov.br/values/t/4709/n6/all/v/93/p/2022"
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "reference" / "municipalities_ibge.csv"
COLUMNS = ["municipality_ibge_code", "municipality_name", "uf", "region", "population", "ddd"]

# Default DDD per UF (the state's main area code).
DEFAULT_DDD = {
    "AC": "68", "AL": "82", "AM": "92", "AP": "96", "BA": "71", "CE": "85",
    "DF": "61", "ES": "27", "GO": "62", "MA": "98", "MG": "31", "MS": "67",
    "MT": "65", "PA": "91", "PB": "83", "PE": "81", "PI": "86", "PR": "41",
    "RJ": "21", "RN": "84", "RO": "69", "RR": "95", "RS": "51", "SC": "48",
    "SE": "79", "SP": "11", "TO": "63",
}  # fmt: skip

# DDD per região imediata where it differs from the UF default.
# Key: UF -> DDD -> region names (matched after removing accents/punctuation).
DDD_BY_REGION: dict[str, dict[str, list[str]]] = {
    "AM": {
        "97": [
            "Coari",
            "Eirunepe",
            "Labrea",
            "Manicore",
            "Sao Gabriel da Cachoeira",
            "Tabatinga",
            "Tefe",
        ]
    },
    "BA": {
        "73": [
            "Eunapolis",
            "Ilheus",
            "Ipiau",
            "Camacan",
            "Itapetinga",
            "Teixeira de Freitas",
            "Jequie",
        ],
        "74": ["Juazeiro", "Jacobina", "Irece", "Xique-Xique", "Senhor do Bonfim"],
        "75": [
            "Feira de Santana",
            "Alagoinhas",
            "Serrinha",
            "Conceicao do Coite",
            "Itaberaba",
            "Santo Antonio de Jesus",
            "Cruz das Almas",
            "Valenca",
            "Ribeira do Pombal",
            "Cicero Dantas",
            "Euclides da Cunha",
            "Jeremoabo",
            "Paulo Afonso",
            "Seabra",
            "Nazare",
        ],
        "77": [
            "Barreiras",
            "Bom Jesus da Lapa",
            "Brumado",
            "Guanambi",
            "Vitoria da Conquista",
            "Santa Maria da Vitoria",
        ],
    },
    "CE": {
        "88": [
            "Acarau",
            "Aracati",
            "Brejo Santo",
            "Camocim",
            "Crateus",
            "Ica",
            "Iguatu",
            "Itapage",
            "Itapipoca",
            "Juazeiro do Norte",
            "Quixada",
            "Russas",
            "Sobral",
            "Sao Benedito",
            "Taua",
        ]
    },
    "ES": {"28": ["Alegre", "Cachoeiro de Itapemirim"]},
    "GO": {
        "61": ["Luziania", "Aguas Lindas de Goias"],
        "64": [
            "Caldas Novas",
            "Catalao",
            "Itumbiara",
            "Jatai",
            "Piracanjuba",
            "Pires do Rio",
            "Quirinopolis",
            "Rio Verde",
            "Sao Luis de Montes Belos",
            "Ipora",
        ],
    },
    "MA": {
        "99": [
            "Acailandia",
            "Bacabal",
            "Balsas",
            "Barra do Corda",
            "Caxias",
            "Chapadinha",
            "Codo",
            "Colinas",
            "Imperatriz",
            "Pedreiras",
            "Presidente Dutra",
            "Sao Joao dos Patos",
            "Timon",
            "Tutoia",
        ]
    },
    "MT": {
        "66": [
            "Alta Floresta",
            "Barra do Garcas",
            "Confresa",
            "Jaciara",
            "Juara",
            "Juina",
            "Peixoto de Azevedo",
            "Primavera do Leste",
            "Rondonopolis",
            "Sinop",
            "Sorriso",
            "Agua Boa",
        ]
    },
    "PA": {
        "93": ["Altamira", "Itaituba", "Santarem", "Oriximina", "Almeirim"],
        "94": ["Maraba", "Parauapebas", "Redencao", "Tucurui", "Xinguara", "Tucuma"],
    },
    "PE": {
        "87": [
            "Afogados da Ingazeira",
            "Araripina",
            "Arcoverde",
            "Belo Jardim",
            "Garanhuns",
            "Petrolina",
            "Salgueiro",
            "Serra Talhada",
        ]
    },
    "PI": {
        "89": [
            "Bom Jesus",
            "Corrente",
            "Floriano",
            "Oeiras",
            "Paulistana",
            "Picos",
            "Sao Joao do Piaui",
            "Sao Raimundo Nonato",
            "Simplicio Mendes",
            "Urucui",
            "Canto do Buriti",
        ]
    },
    "PR": {
        "42": [
            "Ponta Grossa",
            "Guarapuava",
            "Irati",
            "Telemaco Borba",
            "Uniao da Vitoria",
            "Pitanga",
            "Laranjeiras do Sul",
        ],
        "43": [
            "Londrina",
            "Apucarana",
            "Cornelio Procopio",
            "Ibaiti",
            "Ivaipora",
            "Santo Antonio da Platina",
        ],
        "44": [
            "Maringa",
            "Campo Mourao",
            "Cianorte",
            "Loanda",
            "Paranacity",
            "Paranavai",
            "Umuarama",
        ],
        "45": ["Cascavel", "Foz do Iguacu", "Toledo", "Marechal Candido Rondon"],
        "46": ["Francisco Beltrao", "Pato Branco", "Dois Vizinhos"],
    },
    "RJ": {
        "22": [
            "Cabo Frio",
            "Campos dos Goytacazes",
            "Itaperuna",
            "Macae",
            "Nova Friburgo",
            "Santo Antonio de Padua",
        ],
        "24": ["Angra dos Reis", "Petropolis", "Resende", "Tres Rios", "Valenca", "Volta Redonda"],
    },
    "RS": {
        "53": ["Bage", "Camaqua", "Pelotas", "Santana do Livramento"],
        "54": [
            "Bento Goncalves",
            "Caxias do Sul",
            "Erechim",
            "Passo Fundo",
            "Marau",
            "Nonoai",
            "Nova Prata",
            "Soledade",
            "Tapejara",
            "Vacaria",
            "Lagoa Vermelha",
            "Carazinho",
        ],
        "55": [
            "Cruz Alta",
            "Ijui",
            "Santa Maria",
            "Santa Rosa",
            "Santiago",
            "Santo Angelo",
            "Sao Borja",
            "Sao Luiz Gonzaga",
            "Uruguaiana",
            "Tres Passos",
            "Tres de Maio",
            "Cerro Largo",
            "Frederico Westphalen",
            "Palmeira das Missoes",
            "Sao Gabriel",
        ],
    },
    "SC": {
        "47": [
            "Blumenau",
            "Brusque",
            "Itajai",
            "Joinville",
            "Rio do Sul",
            "Ibirama",
            "Mafra",
            "Sao Bento do Sul",
            "Ituporanga",
        ],
        "49": [
            "Cacador",
            "Chapeco",
            "Concordia",
            "Curitibanos",
            "Joacaba",
            "Lages",
            "Maravilha",
            "Sao Lourenco do Oeste",
            "Sao Miguel do Oeste",
            "Videira",
            "Xanxere",
        ],
    },
    "MG": {
        "32": [
            "Juiz de Fora",
            "Alem Paraiba",
            "Cataguases",
            "Muriae",
            "Carangola",
            "Sao Joao Nepomuceno",
            "Uba",
            "Barbacena",
            "Sao Joao del Rei",
        ],
        "33": [
            "Governador Valadares",
            "Teofilo Otoni",
            "Caratinga",
            "Manhuacu",
            "Almenara",
            "Aimores",
            "Mantena",
            "Pedra Azul",
            "Aguas Formosas",
            "Guanhaes",
            "Aracuai",
        ],
        "34": [
            "Uberlandia",
            "Uberaba",
            "Araxa",
            "Ituiutaba",
            "Iturama",
            "Frutal",
            "Monte Carmelo",
            "Patrocinio",
            "Patos de Minas",
        ],
        "35": [
            "Pocos de Caldas",
            "Pouso Alegre",
            "Varginha",
            "Alfenas",
            "Passos",
            "Lavras",
            "Itajuba",
            "Sao Lourenco",
            "Tres Coracoes",
            "Caxambu",
            "Guaxupe",
            "Sao Sebastiao do Paraiso",
            "Tres Pontas",
        ],
        "37": [
            "Divinopolis",
            "Formiga",
            "Oliveira",
            "Piumhi",
            "Campo Belo",
            "Para de Minas",
            "Dores do Indaia",
            "Abaete",
        ],
        "38": [
            "Montes Claros",
            "Januaria",
            "Janauba",
            "Salinas",
            "Sao Francisco",
            "Pirapora",
            "Unai",
            "Diamantina",
            "Curvelo",
            "Espinosa",
            "Capelinha",
        ],
    },
    "SP": {
        "12": ["Sao Jose dos Campos", "Caraguatatuba", "Taubate", "Guaratingueta", "Cruzeiro"],
        "13": ["Santos", "Registro"],
        "14": [
            "Bauru",
            "Botucatu",
            "Jau",
            "Avare",
            "Lins",
            "Marilia",
            "Ourinhos",
            "Piraju",
            "Tupa",
        ],
        "15": ["Sorocaba", "Itapetininga", "Itapeva", "Tatui"],
        "16": [
            "Ribeirao Preto",
            "Araraquara",
            "Sao Carlos",
            "Franca",
            "Ituverava",
            "Sao Joaquim da Barra",
        ],
        "17": [
            "Sao Jose do Rio Preto",
            "Catanduva",
            "Fernandopolis",
            "Jales",
            "Votuporanga",
            "Santa Fe do Sul",
            "Barretos",
        ],
        "18": [
            "Presidente Prudente",
            "Aracatuba",
            "Andradina",
            "Assis",
            "Adamantina",
            "Dracena",
            "Birigui",
            "Presidente Epitacio",
        ],
        "19": [
            "Campinas",
            "Piracicaba",
            "Limeira",
            "Rio Claro",
            "Mogi Guacu",
            "Amparo",
            "Sao Joao da Boa Vista",
            "Sao Jose do Rio Pardo",
            "Araras",
        ],
    },
}


def _normalize(text: str) -> str:
    """Lowercase, no accents, no punctuation: stable matching of region names."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c if c.isalnum() else " " for c in ascii_text.lower()).strip()


def _region_index() -> dict[str, list[tuple[str, str]]]:
    """UF -> [(normalized region name, ddd)]."""
    index: dict[str, list[tuple[str, str]]] = {}
    for uf, by_ddd in DDD_BY_REGION.items():
        index[uf] = [(_normalize(name), ddd) for ddd, names in by_ddd.items() for name in names]
    return index


def ddd_for(uf: str, region_name: str, index: dict[str, list[tuple[str, str]]]) -> str:
    """DDD of an immediate region: first table entry that matches, else the UF default."""
    normalized = _normalize(region_name)
    for key, ddd in index.get(uf, []):
        # IBGE joins neighbouring cities in one region ("Ilhéus - Itabuna"): match tokens.
        if normalized == key or normalized.startswith(key + " "):
            return ddd
    return DEFAULT_DDD[uf]


def _fetch_json(url: str) -> list[dict[str, object]]:
    if not url.startswith("https://"):
        raise ValueError(f"only https URLs are allowed: {url}")
    request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":  # IBGE serves gzip regardless of the header
        raw = gzip.decompress(raw)
    data: list[dict[str, object]] = json.loads(raw)
    return data


def build_rows() -> list[dict[str, str]]:
    population = {str(r["D1C"]): str(r["V"]) for r in _fetch_json(POPULATION_URL)[1:]}
    index = _region_index()
    rows: list[dict[str, str]] = []
    for item in _fetch_json(MUNICIPALITIES_URL):
        code = str(item["id"])
        if code not in population:  # no Censo 2022 value (newly created municipality)
            continue
        immediate = item["regiao-imediata"]  # type: ignore[index]
        uf_info = immediate["regiao-intermediaria"]["UF"]  # type: ignore[index]
        uf = uf_info["sigla"]
        rows.append(
            {
                "municipality_ibge_code": code,
                "municipality_name": str(item["nome"]),
                "uf": uf,
                "region": uf_info["regiao"]["sigla"],
                "population": population[code],
                "ddd": ddd_for(uf, immediate["nome"], index),
            }
        )
    rows.sort(key=lambda r: r["municipality_ibge_code"])
    return rows


def main() -> int:
    rows = build_rows()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} municipalities written to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
