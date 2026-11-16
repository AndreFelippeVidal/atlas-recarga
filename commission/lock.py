"""Lock do lote e remessa simulada (SPEC-003 §4 e §6, task P8.7).

Roda na mesma execução da aprovação final (`approved`), chamado por `review.py`. Sem IA, sem
rede: só copia linhas e escreve dois arquivos no Volume do próprio workspace.

Ordem (cada passo é idempotente, então uma execução interrompida se completa ao repetir o
`approve` num lote que ficou em `approved`):

1. confere `batch_lines` contra os totais do lote;
2. escreve `<batch_id>.csv` e `<batch_id>.sha256` em `/Volumes/<catalog>/commission/remittance`;
3. copia `batch_lines` para `locked_lines` (append-only), só se o lote ainda não tem linhas lá;
4. grava `batches.remittance_sha256`;
5. o chamador faz `approved -> locked` (compare-and-set) e grava o evento.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

HEADER = ("beneficiary_type", "beneficiary_id", "commission_brl")
CENT = Decimal("0.01")
REMITTANCE_VOLUME = "remittance"
LINE_COLUMNS = (
    "beneficiary_type, beneficiary_id, base_amount_brl, tier, rate, commission_brl, flags"
)


def render_remittance(rows: Iterable[tuple[str, str, Decimal]]) -> bytes:
    """CSV determinístico: ordenado por tipo e id, `\\n`, valores com 2 casas, UTF-8."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    for kind, ident, amount in sorted(rows, key=lambda r: (r[0], r[1])):
        writer.writerow((kind, ident, format(Decimal(amount).quantize(CENT), "f")))
    return out.getvalue().encode("utf-8")


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file_text(digest: str, batch_id: str) -> str:
    """Formato do `sha256sum`: `<hash>  <arquivo>`; confere com `sha256sum -c`."""
    return f"{digest}  {batch_id}.csv\n"


def remittance_dir(catalog: str) -> Path:
    return Path("/Volumes") / catalog / "commission" / REMITTANCE_VOLUME


def write_remittance(directory: Path, batch_id: str, content: bytes) -> str:
    """Grava o CSV e o `.sha256` (sobrescreve com o mesmo conteúdo) e devolve o hash."""
    directory.mkdir(parents=True, exist_ok=True)
    digest = sha256_hex(content)
    (directory / f"{batch_id}.csv").write_bytes(content)
    (directory / f"{batch_id}.sha256").write_text(
        sha256_file_text(digest, batch_id), encoding="utf-8"
    )
    return digest


def check_totals(
    rows: Iterable[tuple[str, str, Decimal]], total_pos: Decimal, total_distributor: Decimal
) -> None:
    """As linhas a travar têm de somar o que o lote declara; senão não trava nada."""
    sums = {"pos": Decimal("0"), "distributor": Decimal("0")}
    count = 0
    for kind, _, amount in rows:
        if kind not in sums:
            raise RuntimeError(f"beneficiary_type inesperado: {kind!r}")
        sums[kind] += Decimal(amount)
        count += 1
    if count == 0:
        raise RuntimeError("o lote não tem linhas; nada a travar")
    if sums["pos"] != Decimal(total_pos) or sums["distributor"] != Decimal(total_distributor):
        raise RuntimeError(
            f"as linhas somam PDV {sums['pos']} e distribuidor {sums['distributor']}, mas o lote "
            f"declara {total_pos} e {total_distributor}; o lock foi recusado"
        )


def lock_batch(spark: Any, catalog: str, batch_id: str, directory: Path | None = None) -> str:
    """Passos 1 a 4. Devolve o sha256 da remessa. O status continua com o chamador."""
    c = f"{catalog}.commission"
    header = spark.sql(
        f"SELECT total_pos_brl, total_distributor_brl FROM {c}.batches WHERE batch_id = :b",  # noqa: S608
        args={"b": batch_id},
    ).first()
    if header is None:
        raise RuntimeError(f"{batch_id} não existe")
    rows = [
        (r["beneficiary_type"], r["beneficiary_id"], r["commission_brl"])
        for r in spark.sql(
            "SELECT beneficiary_type, beneficiary_id, commission_brl "  # noqa: S608
            f"FROM {c}.batch_lines WHERE batch_id = :b",
            args={"b": batch_id},
        ).collect()
    ]
    check_totals(rows, header["total_pos_brl"], header["total_distributor_brl"])

    digest = write_remittance(
        directory or remittance_dir(catalog), batch_id, render_remittance(rows)
    )

    spark.sql(
        f"INSERT INTO {c}.locked_lines (batch_id, {LINE_COLUMNS}) "  # noqa: S608
        f"SELECT batch_id, {LINE_COLUMNS} FROM {c}.batch_lines WHERE batch_id = :b "
        f"AND NOT EXISTS (SELECT 1 FROM {c}.locked_lines WHERE batch_id = :b)",
        args={"b": batch_id},
    )
    locked = spark.sql(
        f"SELECT COUNT(*) AS n FROM {c}.locked_lines WHERE batch_id = :b",  # noqa: S608
        args={"b": batch_id},
    ).first()
    if locked is None or int(locked["n"]) != len(rows):
        raise RuntimeError(f"{batch_id}: locked_lines não tem as {len(rows)} linhas do rascunho")
    diverged = spark.sql(
        "SELECT COUNT(*) AS n FROM (SELECT * FROM "  # noqa: S608
        f"(SELECT {LINE_COLUMNS} FROM {c}.batch_lines WHERE batch_id = :b) "
        f"EXCEPT SELECT {LINE_COLUMNS} FROM {c}.locked_lines WHERE batch_id = :b)",
        args={"b": batch_id},
    ).first()
    if diverged is None or int(diverged["n"]) != 0:
        raise RuntimeError(f"{batch_id}: locked_lines diverge de batch_lines; o lock foi recusado")

    spark.sql(
        f"UPDATE {c}.batches SET remittance_sha256 = :h WHERE batch_id = :b",  # noqa: S608
        args={"h": digest, "b": batch_id},
    )
    return digest
