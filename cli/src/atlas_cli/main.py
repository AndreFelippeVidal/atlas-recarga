"""Entry point do `atlas-cli`. Os comandos são stubs até as tasks P4.3 a P4.9."""

from typing import NoReturn

import typer

app = typer.Typer(
    name="atlas-cli",
    help="Gerador determinístico de dados sintéticos da rede de recarga (SPEC-001).",
    no_args_is_help=True,
)
scenario_app = typer.Typer(help="Anomalias injetadas nos dados.", no_args_is_help=True)
app.add_typer(scenario_app, name="scenario")

NOT_IMPLEMENTED_EXIT = 1


def _not_implemented(command: str) -> NoReturn:
    typer.echo(f"atlas-cli {command}: não implementado ainda.", err=True)
    raise typer.Exit(NOT_IMPLEMENTED_EXIT)


@app.command()
def generate() -> None:
    """Gera as entidades em arquivos locais."""
    _not_implemented("generate")


@app.command()
def upload() -> None:
    """Envia os arquivos gerados para o Volume UC /Volumes/atlas/raw/landing/."""
    _not_implemented("upload")


@app.command()
def validate() -> None:
    """Confere os invariantes da SPEC-001 §6 sobre um diretório gerado."""
    _not_implemented("validate")


@scenario_app.command("list")
def scenario_list() -> None:
    """Lista as anomalias disponíveis e seus parâmetros."""
    _not_implemented("scenario list")


if __name__ == "__main__":
    app()
