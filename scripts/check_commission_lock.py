"""Confere o lock e a remessa simulada do lote (SPEC-003 §6 e §8, task P8.7).

Depois de o lote ir a `approved` pelo job `atlas_commission_review` (o lock roda na mesma
execução), o **mantenedor** roda, só com leitura:

    databricks bundle run atlas_commission_deploy -t dev --profile <perfil>   # cria o Volume
    uv run python scripts/check_commission_lock.py --target dev --profile <perfil> \\
        --warehouse-id <id> --batch-id COM-2026-09-v1

Confere: o lote está `locked` e tem `remittance_sha256`; `locked_lines` é igual a `batch_lines`
(linhas e somas); há 1 evento `approved -> locked` por `system`; e o sha256 do CSV no Volume
(baixado com `databricks fs cp`, calculado aqui) é igual a `batches.remittance_sha256` e ao
conteúdo do `.sha256` (critério 7). Sai com 0 ou 1.
"""

from __future__ import annotations

# ruff: noqa: S608  (SQL só com `catalog` de CATALOGS e `batch_id` validado por regex)
import argparse
import hashlib
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from check_commission_draft import CATALOGS, _mark, _run, check_any_batch_id


def _download(profile: str, remote: str, local: Path) -> bytes:
    command = ["databricks", "--profile", profile, "fs", "cp", f"dbfs:{remote}", str(local)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"{result.stderr.strip()} {result.stdout.strip()}")
    return local.read_bytes()


def check(profile: str, warehouse_id: str, catalog: str, batch_id: str) -> list[str]:
    check_any_batch_id(batch_id)
    c = f"{catalog}.commission"
    try:
        header = _run(
            profile,
            warehouse_id,
            f"SELECT status, remittance_sha256 FROM {c}.batches WHERE batch_id = '{batch_id}'",
        )
        agg = (
            "COUNT(*), CAST(COALESCE(SUM(commission_brl), 0) AS DECIMAL(24,2)), "
            "CAST(COALESCE(SUM(base_amount_brl), 0) AS DECIMAL(24,2))"
        )
        drafted = _run(
            profile,
            warehouse_id,
            f"SELECT {agg} FROM {c}.batch_lines WHERE batch_id = '{batch_id}'",
        )[0]
        locked = _run(
            profile,
            warehouse_id,
            f"SELECT {agg} FROM {c}.locked_lines WHERE batch_id = '{batch_id}'",
        )[0]
        diff = _run(
            profile,
            warehouse_id,
            f"SELECT COUNT(*) FROM (SELECT * FROM {c}.batch_lines WHERE batch_id = '{batch_id}' "
            f"EXCEPT SELECT * FROM {c}.locked_lines WHERE batch_id = '{batch_id}')",
        )[0][0]
        events = _run(
            profile,
            warehouse_id,
            f"SELECT COUNT(*) FROM {c}.batch_events WHERE batch_id = '{batch_id}' "
            "AND from_status = 'approved' AND to_status = 'locked' AND role = 'system'",
        )[0][0]
        if not header:
            return [f"FALHA {batch_id} não existe"]
        if header[0][0] != "locked":
            return [
                f"FALHA {batch_id}: status = {header[0][0]!r}, ainda não está 'locked'. Se for "
                "'approved', repita `approve` no job atlas_commission_review (retoma o lock)"
            ]
        volume = f"/Volumes/{catalog}/commission/remittance/{batch_id}"
        with tempfile.TemporaryDirectory() as tmp:
            csv_bytes = _download(profile, f"{volume}.csv", Path(tmp) / "r.csv")
            sha_text = _download(profile, f"{volume}.sha256", Path(tmp) / "r.sha256").decode()
    except (RuntimeError, IndexError) as error:
        return [f"FALHA não consegui ler o lote travado: {error}"]

    if not header:
        return [f"FALHA {batch_id} não existe"]
    status, stored = header[0]
    actual = hashlib.sha256(csv_bytes).hexdigest()
    csv_rows = max(len(csv_bytes.decode().splitlines()) - 1, 0)
    return [
        _mark(status == "locked", f"{batch_id}: status = {status!r} (esperado 'locked')"),
        _mark(
            locked == drafted and int(diff or 0) == 0 and int(locked[0] or 0) > 0,
            f"locked_lines = batch_lines (linhas, somas e conteúdo): {locked[0]} linhas",
        ),
        _mark(int(events or 0) == 1, f"eventos approved -> locked por system: {events}"),
        _mark(actual == stored, f"sha256 do CSV no Volume = batches.remittance_sha256 ({actual})"),
        _mark(sha_text.split()[:1] == [actual], "o arquivo .sha256 traz o mesmo hash"),
        _mark(csv_rows == int(locked[0] or 0), f"o CSV tem {csv_rows} linhas de dados"),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--batch-id", required=True, help="ex.: COM-2026-09-v1")
    args = parser.parse_args(argv)
    out = check(args.profile, args.warehouse_id, CATALOGS[args.target], args.batch_id)
    print("\n".join(out))
    return 1 if any(line.startswith("FALHA") for line in out) else 0


if __name__ == "__main__":
    sys.exit(main())
