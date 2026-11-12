"""Entry point do `atlas-cli`: `generate`, `validate` e `scenario list`; `upload` é stub."""

import re
from datetime import date
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from atlas_cli.exit_codes import ExitCode
from atlas_cli.generate import generate_reference_entities
from atlas_cli.generate_io import OutputFormat
from atlas_cli.incremental import IncrementalError, generate_incremental_day
from atlas_cli.recharges import NoActivePosError
from atlas_cli.reference import Municipalities, ReferenceError, load_municipalities
from atlas_cli.scenarios import catalog, parse_scenarios
from atlas_cli.validate import ValidateError, validate_directory

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


def _parse_incremental_day(value: str) -> date:
    try:
        return date.fromisoformat(value) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else _bad()
    except ValueError:
        return _bad()


def _bad() -> NoReturn:
    raise typer.BadParameter("use uma data válida YYYY-MM-DD", param_hint="--incremental-day")


@app.command()
def generate(
    ctx: typer.Context,
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
            help="Anomalias a injetar (CSV), `all` ou `none`. Veja `atlas-cli scenario list`.",
        ),
    ] = "all",
    out: Annotated[Path, typer.Option("--out", help="Diretório de saída.")] = Path(
        "./data/generated"
    ),
    fmt: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.PARQUET,
    incremental_day: Annotated[
        str | None,
        typer.Option(
            "--incremental-day",
            help="YYYY-MM-DD; gera só as recargas desse dia, sobre os PDVs já gerados em --out.",
        ),
    ] = None,
) -> None:
    """Gera as entidades em arquivos locais (distributors, pos e recharges)."""
    end = _parse_end_month(end_month)
    try:
        chosen = parse_scenarios(scenarios)
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--scenarios") from exc
    try:
        municipalities = load_municipalities()
    except ReferenceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(ExitCode.REFERENCE_DATA_INVALID) from exc
    if incremental_day is not None:
        _run_incremental(ctx, incremental_day, out, seed, rows, fmt, municipalities, chosen)
        return
    try:
        result = generate_reference_entities(
            out=out,
            seed=seed,
            n_distributors=distributors,
            n_pos=pos,
            months=months,
            end_month=end,
            fmt=fmt,
            municipalities=municipalities,
            rows=rows,
            scenarios=chosen,
        )
    except NoActivePosError as exc:
        raise typer.BadParameter(str(exc), param_hint="--pos") from exc
    for path in result.entity_files:
        typer.echo(str(path))
    typer.echo(f"{out / 'recharges'}: {result.rows} recargas em {result.partitions} partições")
    typer.echo(str(result.manifest))


def _run_incremental(
    ctx: typer.Context,
    value: str,
    out: Path,
    seed: int,
    rows: int,
    fmt: OutputFormat,
    municipalities: Municipalities,
    scenarios: tuple[str, ...],
) -> None:
    day = _parse_incremental_day(value)
    ignored = [
        f"--{name.replace('_', '-')}"
        for name in ("months", "end_month", "pos", "distributors")
        if (source := ctx.get_parameter_source(name)) is not None and source.name == "COMMANDLINE"
    ]
    if ignored:
        typer.echo(f"aviso: {', '.join(ignored)} ignorado(s) com --incremental-day.", err=True)
    try:
        result = generate_incremental_day(
            out=out,
            day=day,
            seed=seed,
            rows=rows,
            fmt=fmt,
            municipalities=municipalities,
            scenarios=scenarios,
        )
    except (IncrementalError, NoActivePosError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(ExitCode.INVALID_FLAG) from exc
    verb = "substituída" if result.replaced else "criada"
    typer.echo(f"{out / 'recharges'}: partição dt={day.isoformat()} {verb}, {result.rows} recargas")
    typer.echo(str(result.manifest))


@app.command()
def upload() -> None:
    """Envia os arquivos gerados para o Volume UC /Volumes/atlas/raw/landing/."""
    _not_implemented("upload")


@app.command()
def validate(
    out: Annotated[Path, typer.Option("--out", help="Diretório gerado por `generate`.")] = Path(
        "./data/generated"
    ),
) -> None:
    """Confere os invariantes da SPEC-001 §6 sobre um diretório gerado."""
    try:
        municipalities = load_municipalities()
    except ReferenceError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(ExitCode.REFERENCE_DATA_INVALID) from exc
    try:
        checks = validate_directory(out, municipalities)
    except ValidateError as exc:
        raise typer.BadParameter(str(exc), param_hint="--out") from exc
    for check in checks:
        suffix = f": {check.detail}" if check.detail else ""
        typer.echo(f"[{check.status}] {check.name}{suffix}")
    if any(check.failed for check in checks):
        raise typer.Exit(ExitCode.VALIDATION_FAILED)


@scenario_app.command("list")
def scenario_list() -> None:
    """Lista as anomalias disponíveis e seus parâmetros."""
    for scenario_id, description, parameters in catalog():
        typer.echo(f"{scenario_id}\t{description}")
        for key, value in parameters.items():
            typer.echo(f"  {key}: {value}")


if __name__ == "__main__":
    app()
