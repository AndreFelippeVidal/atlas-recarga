"""Vizinhança entre UFs e pesos regionais de pré-pago (SPEC-001 §4)."""

# Fronteiras terrestres entre UFs. Declarado em uma direção e simetrizado abaixo.
_BORDERS: dict[str, tuple[str, ...]] = {
    "AC": ("AM", "RO"),
    "AL": ("PE", "SE", "BA"),
    "AP": ("PA",),
    "AM": ("RR", "PA", "MT", "RO"),
    "BA": ("SE", "PE", "PI", "TO", "GO", "MG", "ES"),
    "CE": ("RN", "PB", "PE", "PI"),
    "DF": ("GO", "MG"),
    "ES": ("MG", "RJ"),
    "GO": ("TO", "MS", "MT", "MG"),
    "MA": ("PI", "TO", "PA"),
    "MT": ("RO", "PA", "TO", "MS"),
    "MS": ("SP", "PR", "MG"),
    "MG": ("RJ", "SP"),
    "PA": ("RR", "TO"),
    "PB": ("RN", "PE"),
    "PR": ("SP", "SC"),
    "PE": ("PI",),
    "PI": ("TO",),
    "RS": ("SC",),
    "RJ": ("SP",),
    "RN": (),
    "RO": (),
    "RR": (),
    "SC": (),
    "SP": (),
    "SE": (),
    "TO": (),
}


def _symmetrize(borders: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    graph: dict[str, set[str]] = {uf: set() for uf in borders}
    for uf, neighbors in borders.items():
        for other in neighbors:
            graph[uf].add(other)
            graph[other].add(uf)
    return {uf: tuple(sorted(n)) for uf, n in sorted(graph.items())}


UF_NEIGHBORS: dict[str, tuple[str, ...]] = _symmetrize(_BORDERS)

# Peso de pré-pago por região (SPEC-001 §4, coluna `municipality_ibge_code`).
REGION_PREPAID_WEIGHT: dict[str, float] = {"N": 1.4, "NE": 1.3, "CO": 1.0, "SE": 0.9, "S": 0.8}

# Fuso local por UF, em horas em relação ao UTC (SPEC-001 §4, "Fuso e hora local").
# Sem exceções por município no MVP: AC UTC-5; AM, RO, RR, MT e MS UTC-4; o resto UTC-3.
_UTC_MINUS_5 = ("AC",)
_UTC_MINUS_4 = ("AM", "RO", "RR", "MT", "MS")
UF_UTC_OFFSET_HOURS: dict[str, int] = {
    uf: -5 if uf in _UTC_MINUS_5 else -4 if uf in _UTC_MINUS_4 else -3 for uf in UF_NEIGHBORS
}
