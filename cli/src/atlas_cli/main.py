"""Entry point do `atlas-cli`. `generate` cobre as três entidades; o resto é stub até a P4.9."""

import re
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from atlas_cli.exit_codes import ExitCode
from atlas_cli.generate import generate_reference_entities
from atlas_cli.generate_io import OutputFormat
from atlas_cli.recharges import NoActivePosError
from atlas_cli.reference import ReferenceError, load_municipalities
from atlas_cli.scenarios import parse_scenarios

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


def _parse_end_month(value: str | None) -> date:
    if value is None:
        today = date.today()
        return today.replace(day=1)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise typer.BadParameter("use o formato YYYY-MM", param_hint="--end-month")
    return date(int(value[:4]), int(value[5:]), 1)


@app.command()
def generate(
    rows: Annotated[
        int,
        typer.Option("--rows", min=1_000, max=10_000_000, help="Total aproximado de recargas."),
    ] = 2_000_000,
    pos: Annotated[int, typer.Option("--pos", min=1, help="Quantidade de PDVs.")] = 5_000,
    distributors: Annotated[
        int, typer.Option("--distributors", min=1, help="Quantidade de distribuidores.")
    ] = 40,
    months: Annotated[int, typer.Option("--months", min=1, help="Meses retroativos.")] = 12,
    end_month: Annotated[
        str | None, typer.Option("--end-month", help="YYYY-MM; o último mês gerado é este - 1.")
    ] = None,
    seed: Annotated[
        int, typer.Option("--seed", min=0, max=2**32 - 1, help="Mesma seed, mesmos arquivos.")
    ] = 42,
    scenarios: Annotated[
        str,
        typer.Option(
            "--scenarios",
            help="Anomalias (CSV), `all` ou `none`. Validada; a injeção entra na P4.6.",
        ),
    ] = "all",
    out: Annotated[Path, typer.Option("--out", help="Diretório de saída.")] = Path(
        "./data/generated"
    ),
    fmt: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.PARQUET,
) -> None:
    """Gera as entidades em arquivos locais (distributors, pos e recharges)."""
    end = _parse_end_month(end_month)
    try:
        parse_scenarios(scenarios)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--scenarios") from exc
    try:
        municipalities = load_municipalities()
    except ReferenceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(ExitCode.REFERENCE_DATA_INVALID) from exc
    try:
        written, (partitions, total_rows) = generate_reference_entities(
            out=out,
            seed=seed,
            n_distributors=distributors,
            n_pos=pos,
            months=months,
            end_month=end,
            fmt=fmt,
            municipalities=municipalities,
            rows=rows,
        )
    except NoActivePosError as exc:
        raise typer.BadParameter(str(exc), param_hint="--pos") from exc
    for path in written:
        typer.echo(str(path))
    typer.echo(f"{out / 'recharges'}: {total_rows} recargas em {partitions} partições")


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
