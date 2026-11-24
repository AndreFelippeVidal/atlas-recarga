"""Gera os dados de um intervalo de datas, envia para a landing e roda o pipeline (SPEC-012, P14.1).

É o primeiro passo da demo. O mantenedor roda no `dev`, com o bundle já implantado:

    uv run python scripts/load_data.py --from 2026-08-01 --to 2026-10-31 --profile <perfil>

Passos: (1) `atlas-cli generate` da janela base fixa (os PDVs dependem dela); (2)
`--incremental-day` para os dias do intervalo fora da janela base; (3) poda dos dias fora de
`[from, to]`;
(4) `atlas-cli validate`; (5) confere que `pos` e `distributors` são os já carregados e roda
`atlas-cli upload`; (6) `databricks bundle run atlas_daily`. `--dry-run` só imprime o plano e
`--no-run` pula o passo 6. Saídas: `0` ok · `1` validate falhou · `2` flag inválida ou PDVs
diferentes dos já carregados · `4` upload falhou · `5` o `atlas_daily` não terminou com sucesso.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # o atlas-cli e a CLI do Databricks são as únicas coisas que chamamos
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from atlas_cli.entities import month_window
from atlas_cli.manifest import MANIFEST_NAME
from atlas_cli.prune import PruneError, prune_recharges

ROOT = Path(__file__).resolve().parent.parent
MAX_DAYS = 366
# Igual ao catálogo de cada target no databricks.yml.
VOLUMES = {"dev": "/Volumes/atlas_dev/raw/landing/", "demo": "/Volumes/atlas/raw/landing/"}
ENTITY_FILES = ("pos/pos.parquet", "distributors/distributors.parquet")
EXIT_FAILED_VALIDATE, EXIT_INVALID, EXIT_UPLOAD, EXIT_PIPELINE = 1, 2, 4, 5

Run = Callable[[list[str]], int]


class LoadError(Exception):
    """Falha com o código de saída que o script devolve."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Plan:
    first: date
    last: date
    base_first: date
    base_last: date
    outside: tuple[date, ...]  # dias do intervalo fora da janela base (vão por --incremental-day)

    @property
    def days(self) -> int:
        return (self.last - self.first).days + 1


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise LoadError(f"data inválida: {value!r} (use YYYY-MM-DD)", EXIT_INVALID) from exc


def parse_month(value: str) -> date:
    try:
        return date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise LoadError(f"mês inválido: {value!r} (use YYYY-MM)", EXIT_INVALID) from exc


def build_plan(first: date, last: date, base_end_month: date, base_months: int) -> Plan:
    if first > last:
        raise LoadError(f"--from {first} é depois de --to {last}", EXIT_INVALID)
    if (last - first).days + 1 > MAX_DAYS:
        raise LoadError(f"o intervalo passa de {MAX_DAYS} dias", EXIT_INVALID)
    if base_months < 1:
        raise LoadError("--base-months precisa ser ≥ 1", EXIT_INVALID)
    window = month_window(base_end_month, base_months)
    days = (first + timedelta(days=i) for i in range((last - first).days + 1))
    outside = tuple(d for d in days if not window.start <= d <= window.end)
    return Plan(first, last, window.start, window.end, outside)


def _cli(name: str) -> str:
    return str(Path(sys.executable).parent / name)


def generate_command(args: argparse.Namespace) -> list[str]:
    return [
        _cli("atlas-cli"),
        "generate",
        *("--rows", str(args.rows)),
        *("--months", str(args.base_months)),
        *("--end-month", args.base_end_month),
        *("--seed", str(args.seed)),
        *("--out", str(args.out)),
    ]


def incremental_command(args: argparse.Namespace, day: date) -> list[str]:
    return [
        _cli("atlas-cli"),
        "generate",
        *("--incremental-day", day.isoformat()),
        *("--rows", str(args.rows)),
        *("--seed", str(args.seed)),
        *("--out", str(args.out)),
    ]


def validate_command(args: argparse.Namespace) -> list[str]:
    return [_cli("atlas-cli"), "validate", *("--out", str(args.out))]


def upload_command(args: argparse.Namespace) -> list[str]:
    return [
        _cli("atlas-cli"),
        "upload",
        *("--out", str(args.out)),
        *("--profile", args.profile),
        *("--dest", VOLUMES[args.target]),
    ]


def pipeline_command(args: argparse.Namespace) -> list[str]:
    return [
        "databricks",
        "bundle",
        "run",
        "atlas_daily",
        *("-t", args.target),
        *("--profile", args.profile),
    ]


def entity_mismatches(local: dict[str, Any], remote_text: str | None) -> list[str]:
    """`pos` e `distributors` locais que diferem dos já enviados (vazio no primeiro envio)."""
    if remote_text is None:
        return []
    try:
        remote_files: dict[str, Any] = json.loads(remote_text)["files"]
    except (ValueError, KeyError, TypeError):
        return []  # manifest remoto ilegível: o upload trata como ausente
    return [
        name
        for name in ENTITY_FILES
        if name in remote_files and remote_files[name] != local["files"].get(name)
    ]


def describe(plan: Plan, args: argparse.Namespace) -> list[str]:
    lines = [
        f"intervalo: {plan.first} a {plan.last} ({plan.days} dias) no target {args.target}",
        f"janela base (fixa): {plan.base_first} a {plan.base_last}, seed {args.seed}, "
        f"rows {args.rows}",
        f"dias fora da janela base (--incremental-day): {len(plan.outside)}",
        f"poda: tudo fora de {plan.first} a {plan.last}",
        f"destino: {VOLUMES[args.target]}",
        "1) " + " ".join(generate_command(args)),
    ]
    if plan.outside:
        lines.append(
            f"2) {len(plan.outside)}x " + " ".join(incremental_command(args, plan.outside[0]))
        )
    lines += [
        "3) prune_recharges",
        "4) " + " ".join(validate_command(args)),
        "5) " + " ".join(upload_command(args)),
        "6) " + ("(pulado: --no-run)" if args.no_run else " ".join(pipeline_command(args))),
    ]
    return lines


def reset_out(out: Path) -> None:
    """Apaga uma saída anterior do `generate` (reproduzível); recusa uma pasta que não é uma."""
    if not out.exists() or not any(out.iterdir()):
        return
    if not (out / MANIFEST_NAME).is_file():
        raise LoadError(f"{out} não está vazia nem é uma saída do atlas-cli", EXIT_INVALID)
    shutil.rmtree(out)


def _run(command: list[str]) -> int:
    return subprocess.run(command, check=False, cwd=ROOT).returncode  # noqa: S603


def execute(
    args: argparse.Namespace,
    plan: Plan,
    run: Run,
    read_remote_manifest: Callable[[], str | None],
) -> None:
    def step(label: str, command: list[str], code: int) -> None:
        print(f"== {label}")
        if run(command) != 0:
            raise LoadError(f"falhou: {label}", code)

    reset_out(args.out)
    step("generate (janela base)", generate_command(args), EXIT_INVALID)
    for day in plan.outside:
        step(f"incremental {day}", incremental_command(args, day), EXIT_INVALID)
    print(f"== poda para {plan.first} a {plan.last}")
    try:
        result = prune_recharges(args.out, plan.first, plan.last)
    except PruneError as exc:
        raise LoadError(str(exc), EXIT_INVALID) from exc
    print(f"{result.kept_partitions} partições, {result.kept_rows} recargas")
    if result.kept_partitions == 0:
        raise LoadError("o intervalo não tem nenhum dia gerado", EXIT_INVALID)
    step("validate", validate_command(args), EXIT_FAILED_VALIDATE)

    local = json.loads((args.out / MANIFEST_NAME).read_text(encoding="utf-8"))
    bad = entity_mismatches(local, read_remote_manifest())
    if bad:
        raise LoadError(
            f"{', '.join(bad)} diferem do que já está na landing: use a mesma --seed, --rows e "
            f"janela base ({plan.base_first} a {plan.base_last}) da carga anterior",
            EXIT_INVALID,
        )
    step("upload", upload_command(args), EXIT_UPLOAD)
    if args.no_run:
        print("== atlas_daily pulado (--no-run)")
        return
    step("atlas_daily", pipeline_command(args), EXIT_PIPELINE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--from", dest="first", required=True, help="YYYY-MM-DD (inclusiva)")
    parser.add_argument("--to", dest="last", required=True, help="YYYY-MM-DD (inclusiva)")
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--target", choices=sorted(VOLUMES), default="dev")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--rows", type=int, default=2_000_000)
    parser.add_argument("--base-end-month", default="2026-11", help="YYYY-MM (último mês = este-1)")
    parser.add_argument("--base-months", type=int, default=12)
    parser.add_argument("--out", type=Path, default=Path("./data/generated-range"))
    parser.add_argument("--no-run", action="store_true", help="não dispara o atlas_daily")
    parser.add_argument("--dry-run", action="store_true", help="só imprime o plano")
    return parser


def main(
    argv: Sequence[str] | None = None,
    run: Run = _run,
    volume_factory: Callable[[str], Any] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = build_plan(
            parse_day(args.first),
            parse_day(args.last),
            parse_month(args.base_end_month),
            args.base_months,
        )
        print("\n".join(describe(plan, args)))
        if args.dry_run:
            return 0

        def read_remote() -> str | None:
            factory = volume_factory
            if factory is None:
                from atlas_cli.upload import DatabricksVolume

                factory = DatabricksVolume
            text: str | None = factory(args.profile).read_text(
                VOLUMES[args.target].rstrip("/") + "/" + MANIFEST_NAME
            )
            return text

        execute(args, plan, run, read_remote)
    except LoadError as exc:
        print(f"FALHA: {exc}", file=sys.stderr)
        return exc.code
    print("OK: dados carregados e pipeline concluído" if not args.no_run else "OK: dados enviados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
