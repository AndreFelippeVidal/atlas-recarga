"""Lógica pura de `scripts/check_consistency.py` (P13.2). Sem workspace."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_consistency as c  # noqa: E402

EXPECTED = Decimal("4122460.00")


def _dashboard() -> dict[str, Any]:
    return json.loads(c.DASHBOARD.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _reading(name: str, *values: str, error: str | None = None) -> c.Reading:
    return c.Reading(name, values=[Decimal(v) for v in values], error=error)


def test_todos_iguais_passa() -> None:
    readings = [_reading(n, "4122460.00") for n in ("AI/BI", "Genie", "agente", "MCP", "React")]
    lines = c.evaluate(EXPECTED, readings)
    assert len(lines) == 5
    assert all(line.startswith("ok") for line in lines)


def test_divergencia_de_um_centavo_falha() -> None:
    lines = c.evaluate(EXPECTED, [_reading("MCP", "4122460.01"), _reading("React", "4122460.00")])
    assert lines[0].startswith("FALHA MCP")
    assert "4122460.01" in lines[0]
    assert lines[1].startswith("ok")


def test_consumidor_fora_do_ar_falha_sem_derrubar_os_outros() -> None:
    def boom() -> c.Reading:
        raise ConnectionError("sem rota")

    bad = c.read_safely("agente", boom)
    lines = c.evaluate(EXPECTED, [bad, _reading("React", "4122460.00")])
    assert lines[0].startswith("FALHA agente") and "ConnectionError" in lines[0]
    assert lines[1].startswith("ok")


def test_sem_valor_falha() -> None:
    assert c.evaluate(EXPECTED, [_reading("Genie")])[0].startswith("FALHA Genie")


def test_referencia_ausente_falha() -> None:
    assert c.evaluate(None, [_reading("React", "1")])[0].startswith("FALHA referência")


def test_agente_com_varios_valores_basta_conter_o_esperado() -> None:
    text = "A receita bruta de outubro foi **R$ 4.122.460,00**, contra R$ 3.900.000,50 em setembro."
    reading = c.Reading("agente", values=c.extract_brl(text))
    assert c.evaluate(EXPECTED, [reading])[0].startswith("ok")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("R$ 4.122.460,00", [Decimal("4122460.00")]),
        ("R$4.122.460,00 e R$ 4.122.460,00", [Decimal("4122460.00")]),
        ("R$ 12,50", [Decimal("12.50")]),
        ("R$ 4122460.00", [Decimal("4122460.00")]),
        ("sem valor monetário", []),
        ("receita de 4,1 milhões", []),
    ],
)
def test_extract_brl(text: str, expected: list[Decimal]) -> None:
    assert c.extract_brl(text) == expected


def test_message_text_junta_so_itens_message() -> None:
    response = {
        "output": [
            {"type": "function_call", "arguments": '{"text": "ignorar"}'},
            {"type": "message", "content": [{"type": "output_text", "text": "R$ 1,00"}]},
        ]
    }
    assert c.message_text(response) == "R$ 1,00"
    assert c.message_text({}) == ""


def test_dashboard_query_le_o_card_do_dashboard_versionado() -> None:
    sql = c.dashboard_query(_dashboard(), "atlas_dev", "2026-10")
    assert "MEASURE(gross_revenue)" in sql
    assert "atlas_dev.semantic.mv_recharges" in sql
    assert "DATE'2026-10-01'" in sql


def test_dashboard_query_recusa_card_que_nao_usa_a_metric_view() -> None:
    dashboard = _dashboard()
    dashboard["datasets"][0]["asset_name"] = "fct_recharges"
    with pytest.raises(ValueError, match="mv_recharges"):
        c.dashboard_query(dashboard, "atlas_dev", "2026-10")


def test_dashboard_query_recusa_card_ausente() -> None:
    with pytest.raises(ValueError, match="não está no dashboard"):
        c.dashboard_query({"datasets": [], "pages": []}, "atlas_dev", "2026-10")


def test_referencia_le_so_o_gold_aprovado() -> None:
    sql = c.reference_query("atlas_dev", "2026-10")
    assert "atlas_dev.gold.fct_recharges" in sql
    assert "status = 'approved'" in sql
    assert "semantic" not in sql


@pytest.mark.parametrize("catalog", ["atlas; DROP", "a.b", "", "a b"])
def test_catalogo_invalido_e_recusado(catalog: str) -> None:
    with pytest.raises(ValueError, match="catálogo"):
        c.reference_query(catalog, "2026-10")
    with pytest.raises(ValueError, match="catálogo"):
        c.dashboard_query(_dashboard(), catalog, "2026-10")


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "26-10", "2026-10-01", "x"])
def test_mes_invalido_e_recusado(month: str) -> None:
    with pytest.raises(ValueError, match="mês"):
        c.reference_query("atlas_dev", month)


def test_month_phrase() -> None:
    assert c.month_phrase("2026-10") == "outubro de 2026"
    assert c.month_phrase("2026-03") == "março de 2026"


def test_genie_value() -> None:
    result = {"statement_response": {"result": {"data_array": [["4122460.00"]]}}}
    assert c.genie_value(result) == EXPECTED
    assert c.genie_value({}) is None
    assert c.genie_value({"statement_response": {"result": {"data_array": [["abc"]]}}}) is None
