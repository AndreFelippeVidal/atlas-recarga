import pytest
from atlas_cli.exit_codes import ExitCode
from atlas_cli.main import NOT_IMPLEMENTED_EXIT, app
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


@pytest.mark.parametrize("args", [["upload"], ["validate"], ["scenario", "list"]])
def test_stubs_exit_not_implemented(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == NOT_IMPLEMENTED_EXIT
    assert "não implementado" in result.output


def test_exit_codes_match_spec() -> None:
    assert [c.value for c in ExitCode] == [0, 2, 3, 4]
