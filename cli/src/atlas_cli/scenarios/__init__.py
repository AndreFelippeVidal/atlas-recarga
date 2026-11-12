"""Cenários (anomalias injetadas) da SPEC-001 §5: ids, catálogo e injetor."""

SCENARIO_IDS = (
    "regional_drop",
    "fractioning",
    "duplicates",
    "null_pos",
    "unknown_pos",
    "late_arrival",
    "negative_amount",
)


def parse_scenarios(value: str) -> tuple[str, ...]:
    """`all` | `none` | CSV de ids. Levanta ValueError para id desconhecido."""
    value = value.strip()
    if value == "all":
        return SCENARIO_IDS
    if value in ("none", ""):
        return ()
    chosen = tuple(part.strip() for part in value.split(","))
    unknown = [c for c in chosen if c not in SCENARIO_IDS]
    if unknown:
        raise ValueError(f"cenário desconhecido: {', '.join(unknown)}")
    return chosen


def catalog() -> list[tuple[str, str, dict[str, str]]]:
    """(id, descrição, parâmetros) de cada cenário, na ordem da SPEC-001 §5."""
    from atlas_cli.scenarios import (
        duplicates,
        fractioning,
        late_arrival,
        negative_amount,
        null_pos,
        regional_drop,
        unknown_pos,
    )

    entries = {
        regional_drop.ID: (regional_drop.DESCRIPTION, regional_drop.PARAMETERS),
        fractioning.Fractioning.id: (
            fractioning.Fractioning.description,
            fractioning.Fractioning.parameters,
        ),
        duplicates.ID: (duplicates.DESCRIPTION, duplicates.PARAMETERS),
        null_pos.NullPos.id: (null_pos.NullPos.description, null_pos.NullPos.parameters),
        unknown_pos.UnknownPos.id: (
            unknown_pos.UnknownPos.description,
            unknown_pos.UnknownPos.parameters,
        ),
        late_arrival.ID: (late_arrival.DESCRIPTION, late_arrival.PARAMETERS),
        negative_amount.NegativeAmount.id: (
            negative_amount.NegativeAmount.description,
            negative_amount.NegativeAmount.parameters,
        ),
    }
    return [(i, *entries[i]) for i in SCENARIO_IDS]
