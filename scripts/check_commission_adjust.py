"""Confere o lote de ajuste ADJ (SPEC-003 §7, task P8.10).

Depois de rodar o job `atlas_commission_draft` com `adjust_batch_id`, o **mantenedor** roda, só
com leitura:

    uv run python scripts/check_commission_adjust.py --target dev \\
        --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-ADJ-1

Confere: o lote é um ajuste; a reconciliação do acumulado (`locked_lines` do mês + linhas do
ajuste x recálculo SQL) está `passed` com diferenças 0.00; o cabeçalho soma as linhas; nenhuma
linha tem flag; `version` é o `n` do `batch_id`. Sai com 0 ou 1.
"""

from __future__ import annotations

# ruff: noqa: S608  (SQL só com `catalog` de CATALOGS e `batch_id` validado por regex)
import argparse
import re
import sys
from collections.abc import Sequence

from check_commission_draft import CATALOGS, _mark, _run, check_batch_id
from check_commission_reconciliation import check as check_reconciliation

_ADJ = re.compile(r"^COM-\d{4}-\d{2}-ADJ-(\d+)$")


def check(profile: str, warehouse_id: str, catalog: str, batch_id: str) -> list[str]:
    check_batch_id(batch_id)
    match = _ADJ.fullmatch(batch_id)
    if match is None:
        return [f"FALHA {batch_id} não é um lote de ajuste (COM-YYYY-MM-ADJ-n)"]
    c = f"{catalog}.commission"
    try:
        head = _run(
            profile,
            warehouse_id,
            "SELECT status, version, total_pos_brl, total_distributor_brl "
            f"FROM {c}.batches WHERE batch_id = '{batch_id}'",
        )
        sums = _run(
            profile,
            warehouse_id,
            "SELECT COUNT(*), "
            "COALESCE(SUM(CASE WHEN beneficiary_type = 'pos' THEN commission_brl END), 0), "
            "COALESCE(SUM(CASE WHEN beneficiary_type = 'distributor' THEN commission_brl END), 0), "
            "COUNT_IF(size(flags) > 0) "
            f"FROM {c}.batch_lines WHERE batch_id = '{batch_id}'",
        )
    except RuntimeError as error:
        return [f"FALHA não consegui ler o lote: {error}"]
    if len(head) != 1:
        return [f"FALHA {batch_id} não existe"]
    status, version, total_pos, total_dist = head[0]
    n, pos, dist, flagged = sums[0]
    out = [
        _mark(
            int(version) == int(match.group(1)),
            f"{batch_id}: status = {status}, version = {version}",
        ),
        _mark(n != "0", f"{n} linhas de diferença"),
        _mark(float(pos) == float(total_pos), f"cabeçalho PDV {total_pos} = soma das linhas {pos}"),
        _mark(
            float(dist) == float(total_dist),
            f"cabeçalho distribuidor {total_dist} = soma das linhas {dist}",
        ),
        _mark(flagged == "0", f"{flagged} linhas com flag (esperado 0)"),
    ]
    return out + check_reconciliation(profile, warehouse_id, catalog, batch_id)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--batch-id", required=True, help="ex.: COM-2026-10-ADJ-1")
    args = parser.parse_args(argv)
    out = check(args.profile, args.warehouse_id, CATALOGS[args.target], args.batch_id)
    print("\n".join(out))
    return 1 if any(line.startswith("FALHA") for line in out) else 0


if __name__ == "__main__":
    sys.exit(main())
