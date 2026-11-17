from pathlib import Path

import pytest
from agent_server.config import load_config
from agent_server.prompts import PROMPTS_DIR, PromptError, load_prompt


def test_default_prompt_version_has_a_file() -> None:
    version = load_config({}).prompt_version
    assert (PROMPTS_DIR / f"{version}.md").is_file()
    assert load_prompt(version)


@pytest.mark.parametrize(
    "bad", ["", "../v1", "a/b", "..", "v1/../v1", ".hidden", "v 1", "v1.md\n", "v1\n"]
)
def test_prompt_version_cannot_escape_the_directory(bad: str) -> None:
    with pytest.raises(PromptError):
        load_prompt(bad)


def test_missing_version_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="não existe"):
        load_prompt("v999", tmp_path)


def test_loads_from_directory(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text("  texto\n", encoding="utf-8")
    assert load_prompt("t", tmp_path) == "texto"


def test_v1_encodes_the_spec_rules() -> None:
    """As regras da SPEC-005 §4 e a lista fechada de tools (§3) estão no texto."""
    text = load_prompt("v1")
    for tool in ("ask_genie", "fn_list_metrics", "fn_metric_by_region", "fn_compare_months"):
        assert f"`{tool}" in text
    assert "Fonte:" in text and "semantic.mv_recharges" in text
    assert "último mês fechado" in text and "R$ 1.234,56" in text
    assert "PT-BR" in text
    assert "Recuse sem chamar nenhuma tool" in text
    for forbidden in ("commission", "gold", "silver", "bronze"):
        assert forbidden in text  # citados para recusar, nunca como fonte


def test_v1_does_not_hardcode_a_month_as_today() -> None:
    assert "Nunca use o mês da data de hoje" in load_prompt("v1")
