"""Regras de cálculo da comissão (SPEC-003 §2).

Módulo puro: sem PySpark, sem I/O, sem IA (ADR-0010). Todo dinheiro é `Decimal`.
O corte por `closed_date` não é feito aqui: o chamador entrega o volume já cortado.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

CENT = Decimal("0.01")
DISTRIBUTOR_RATE = Decimal("0.03")


@dataclass(frozen=True)
class Tier:
    name: str
    floor: Decimal  # limite inferior inclusivo do volume mensal aprovado (R$)
    rate: Decimal


# Ordem crescente de `floor`. A faixa vale inteira (não progressiva).
TIERS: tuple[Tier, ...] = (
    Tier("bronze", Decimal("0"), Decimal("0.02")),
    Tier("silver", Decimal("5000.00"), Decimal("0.03")),
    Tier("gold", Decimal("20000.00"), Decimal("0.04")),
    Tier("diamond", Decimal("50000.00"), Decimal("0.05")),
)


def round_brl(value: Decimal) -> Decimal:
    """Arredonda para centavos com ROUND_HALF_EVEN (por linha)."""
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def _check_volume(volume: Decimal) -> None:
    if not volume.is_finite():
        raise ValueError(f"volume must be finite, got {volume}")
    if volume < 0:
        raise ValueError(f"volume must be >= 0, got {volume}")


def tier_for(volume: Decimal) -> Tier:
    """Faixa do PDV: a de maior limite inferior menor ou igual ao volume."""
    _check_volume(volume)
    # TIERS está em ordem crescente de floor: o primeiro match de trás para frente é o maior.
    return next(t for t in reversed(TIERS) if volume >= t.floor)


def pos_commission(volume: Decimal) -> tuple[Tier, Decimal]:
    """Comissão do PDV, já arredondada. Volume zero não gera linha: use `has_line`."""
    tier = tier_for(volume)
    return tier, round_brl(volume * tier.rate)


def distributor_commission(total_volume: Decimal) -> Decimal:
    """3% sobre a soma do volume aprovado dos PDVs do distribuidor, arredondado."""
    _check_volume(total_volume)
    return round_brl(total_volume * DISTRIBUTOR_RATE)


def has_line(volume: Decimal) -> bool:
    """PDV (ou distribuidor) com volume zero não gera linha."""
    _check_volume(volume)
    return volume > 0


def batch_total(lines: Iterable[Decimal]) -> Decimal:
    """Total do lote: soma das linhas, que já devem estar em centavos.

    Rejeita linha não arredondada: o total nunca é recalculado nem corrigido em silêncio.
    """
    total = Decimal("0.00")
    for x in lines:
        if x != round_brl(x):
            raise ValueError(f"line must already be rounded to cents, got {x}")
        total += x
    return total
