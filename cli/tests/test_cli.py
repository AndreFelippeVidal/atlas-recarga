import re

import pytest
from atlas_cli.exit_codes import ExitCode
from atlas_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("generate", "upload", "validate", "scenario"):
        assert name in result.output


def test_scenario_help_lists_list() -> None:
    result = runner.invoke(app, ["scenario", "--help"])
    assert result.exit_code == 0
    assert "list" in result.output


def test_upload_requires_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_DATABRICKS_PROFILE", raising=False)
    result = runner.invoke(app, ["upload"])
    assert result.exit_code == 2
    assert "profile" in re.sub(r"\x1b\[[0-9;]*m|[│╭╰╮─\n]", " ", result.output)


def test_exit_codes_match_spec() -> None:
    assert [c.value for c in ExitCode] == [0, 1, 2, 3, 4]
