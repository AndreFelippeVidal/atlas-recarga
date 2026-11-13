"""Prova o critério 4 da SPEC-002 §5: PDV com município fora da referência derruba o pipeline.

Roda só no `dev` (nunca no `demo`) e é reversível. O **mantenedor** executa:

    uv run python scripts/check_silver_pos_integrity.py --profile andrevidal --yes

Sem `--yes` só imprime o plano. Com `--yes`:
1. baixa `pos/pos.parquet` do landing para uma pasta local de backup;
2. troca o `municipality_ibge_code` da primeira linha por um código fora da referência;
3. roda `atlas_medallion` e espera **falha** (`pos_municipality_known`);
4. restaura o arquivo original (sempre, mesmo se algo der errado) e confere o sha256;
5. com `--rerun-after`, roda o pipeline de novo para voltar ao verde.

Sai com 0 se o pipeline falhou como esperado e o landing foi restaurado.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pyarrow.parquet as pq

LANDING = {"dev": "/Volumes/atlas_dev/raw/landing"}  # só dev: o demo nunca é tocado
POS_FILE = "pos/pos.parquet"
INVALID_MUNICIPALITY = "9999999"  # 7 dígitos, fora da referência IBGE
EXPECTED_EXPECTATION = "pos_municipality_known"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corrupt_municipality(src: Path, dst: Path) -> None:
    """Copia `src` para `dst` trocando o município da primeira linha por um código inválido."""
    table = pq.read_table(src)
    column = table.schema.get_field_index("municipality_ibge_code")
    if column < 0:
        raise ValueError("coluna municipality_ibge_code ausente em pos.parquet")
    values = table.column(column).to_pylist()
    if not values:
        raise ValueError("pos.parquet está vazio")
    values[0] = INVALID_MUNICIPALITY
    import pyarrow as pa

    patched = table.set_column(
        column, table.schema.field(column), pa.array(values, type=table.schema.field(column).type)
    )
    pq.write_table(patched, dst)


def _cli(profile: str, *args: str) -> subprocess.CompletedProcess[str]:
    command = ["databricks", "--profile", profile, *args]
    return subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603


def _copy(profile: str, src: str, dst: str) -> None:
    result = _cli(profile, "fs", "cp", src, dst, "--overwrite")
    if result.returncode != 0:
        raise RuntimeError(f"fs cp falhou ({src} -> {dst}): {result.stderr.strip()}")


def _run_pipeline(profile: str, target: str) -> subprocess.CompletedProcess[str]:
    return _cli(profile, "bundle", "run", "atlas_medallion", "-t", target)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--target", choices=sorted(LANDING), default="dev")
    parser.add_argument("--yes", action="store_true", help="executa de verdade (sem: só o plano)")
    parser.add_argument("--rerun-after", action="store_true", help="roda o pipeline após restaurar")
    parser.add_argument("--backup-dir", type=Path, help="onde guardar o backup local")
    args = parser.parse_args(argv)

    remote = f"dbfs:{LANDING[args.target]}/{POS_FILE}"
    print(f"alvo: {remote}")
    if not args.yes:
        print("plano: backup -> corromper 1 linha -> rodar pipeline (esperado: falha) -> restaurar")
        print("nada foi alterado; rode de novo com --yes")
        return 0

    work = args.backup_dir or Path(tempfile.mkdtemp(prefix="atlas-pos-backup-"))
    work.mkdir(parents=True, exist_ok=True)
    original = work / "pos.original.parquet"
    corrupted = work / "pos.corrupted.parquet"

    _copy(args.profile, remote, str(original))
    original_sha = sha256(original)
    print(f"backup local: {original} (sha256 {original_sha[:12]}…)")

    failed_as_expected = False
    restored = False
    try:
        corrupt_municipality(original, corrupted)
        _copy(args.profile, str(corrupted), remote)
        print(f"landing alterado: 1 PDV com município {INVALID_MUNICIPALITY}; rodando o pipeline…")
        run = _run_pipeline(args.profile, args.target)
        output = run.stdout + run.stderr
        if run.returncode == 0:
            print("FALHA o pipeline terminou com sucesso: a expectation não foi aplicada")
        else:
            failed_as_expected = True
            named = EXPECTED_EXPECTATION in output
            print(f"ok    o pipeline falhou (código {run.returncode})")
            print(
                f"{'ok   ' if named else 'aviso'} "
                f"{'a saída cita' if named else 'a saída NÃO cita'} {EXPECTED_EXPECTATION}"
            )
            print("--- fim da saída ---\n" + "\n".join(output.strip().splitlines()[-15:]))
    finally:
        _copy(args.profile, str(original), remote)
        check = work / "pos.restored.parquet"
        _copy(args.profile, remote, str(check))
        restored = sha256(check) == original_sha
        print(f"{'ok   ' if restored else 'FALHA'} landing restaurado (sha256 confere)")
        if not restored:
            print(f"restaure à mão: databricks fs cp {original} {remote} --overwrite")
        else:
            shutil.rmtree(work, ignore_errors=True) if args.backup_dir is None else None

    if args.rerun_after and restored:
        rerun = _run_pipeline(args.profile, args.target)
        print(f"{'ok   ' if rerun.returncode == 0 else 'FALHA'} pipeline de volta ao verde")
        if rerun.returncode != 0:
            return 1
    return 0 if failed_as_expected and restored else 1


if __name__ == "__main__":
    sys.exit(main())
