"""Confere a reconciliação do lote de comissão (SPEC-003 §5 e §8, task P8.4).

Depois do job `atlas_commission_draft` (que agora inclui `reconcile_draft`), o **mantenedor**
roda, só com leitura:

    uv run python scripts/check_commission_reconciliation.py --target dev \\
        --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-v1

Confere em `commission.reconciliation`: exatamente 1 linha do lote, `status = 'passed'`, todas as
diferenças em 0.00 e `lines_compared` = linhas do lote em `batch_lines`. Sai com 0 ou 1.
"""

from __future__ import annotations

# ruff: noqa: S608  (SQL só com `catalog` de CATALOGS e `batch_id` validado por regex)
import argparse
import sys
from collections.abc import Sequence

from check_commission_draft import CATALOGS, _mark, _run, check_any_batch_id


def check(profile: str, warehouse_id: str, catalog: str, batch_id: str) -> list[str]:
    check_any_batch_id(batch_id)
    c = f"{catalog}.commission"
    try:
        rows = _run(
            profile,
            warehouse_id,
            "SELECT status, lines_compared, max_line_diff_brl, total_diff_brl, "
            "pos_control_diff_brl, distributor_control_diff_brl "
            f"FROM {c}.reconciliation WHERE batch_id = '{batch_id}'",
        )
        lines = _run(
            profile,
            warehouse_id,
            f"SELECT COUNT(*) FROM {c}.batch_lines WHERE batch_id = '{batch_id}'",
        )
    except RuntimeError as error:
        return [f"FALHA não consegui ler a reconciliação: {error}"]

    if len(rows) != 1:
        return [f"FALHA {len(rows)} linha(s) de reconciliação para {batch_id}; esperado 1"]
    status, compared, max_line, total, pos, dist = rows[0]
    zero = {"0.00", "-0.00"}
    return [
        _mark(status == "passed", f"{batch_id}: status = {status}"),
        _mark(
            compared == lines[0][0] and compared != "0",
            f"{compared} linhas comparadas = {lines[0][0]} linhas do lote",
        ),
        _mark(max_line in zero, f"maior diferença por linha: {max_line}"),
        _mark(total in zero, f"diferença no total (cabeçalho x recálculo): {total}"),
        _mark(pos in zero, f"controle PDV x fct_recharges: {pos}"),
        _mark(dist in zero, f"controle distribuidor x soma por distribuidor: {dist}"),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--batch-id", required=True, help="ex.: COM-2026-10-v1")
    args = parser.parse_args(argv)
    out = check(args.profile, args.warehouse_id, CATALOGS[args.target], args.batch_id)
    print("\n".join(out))
    return 1 if any(line.startswith("FALHA") for line in out) else 0


if __name__ == "__main__":
    sys.exit(main())
