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


def test_upload_stub_exits_not_implemented() -> None:
    result = runner.invoke(app, ["upload"])
    assert result.exit_code == NOT_IMPLEMENTED_EXIT
    assert "não implementado" in result.output


def test_exit_codes_match_spec() -> None:
    assert [c.value for c in ExitCode] == [0, 1, 2, 3, 4]
