"""Ids de cenários da SPEC-001 §5. A injeção em si entra na P4.6."""

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
