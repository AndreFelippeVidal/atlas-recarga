"""Confere os flags de revisão do lote de comissão (SPEC-003 §5 e §8, task P8.5).

Depois do job `atlas_commission_draft` (que agora inclui `flag_draft`), o **mantenedor** roda,
só com leitura:

    uv run python scripts/check_commission_flags.py --target dev \\
        --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-v1 --expect-fractioning

Confere em `commission.batch_lines`: só valores do conjunto de flags da SPEC; nenhum flag em
linha de distribuidor; `closed_pos` = PDVs com linha e `closed_date` no mês; e, com
`--expect-fractioning` (dataset com o cenário `fractioning`), pelo menos 3 PDVs com
`fractioning_suspect` (critério 3 da SPEC-003 §8).
Imprime a contagem por flag. Sai com 0 ou 1.
"""

from __future__ import annotations

# ruff: noqa: S608  (SQL só com `catalog` de CATALOGS e `batch_id` validado por regex)
import argparse
import sys
from collections.abc import Sequence

from check_commission_draft import CATALOGS, _mark, _run, check_batch_id

ALLOWED = ("spike_3x", "fractioning_suspect", "tier_jump", "closed_pos")


def check(
    profile: str,
    warehouse_id: str,
    catalog: str,
    batch_id: str,
    expect_fractioning: bool = False,
) -> list[str]:
    check_batch_id(batch_id)
    c = f"{catalog}.commission"
    lines = f"{c}.batch_lines"
    try:
        counts = dict(
            _run(
                profile,
                warehouse_id,
                f"SELECT flag, COUNT(*) FROM (SELECT explode(flags) AS flag FROM {lines} "
                f"WHERE batch_id = '{batch_id}') GROUP BY flag",
            )
        )
        on_distributor = _run(
            profile,
            warehouse_id,
            f"SELECT COUNT(*) FROM {lines} WHERE batch_id = '{batch_id}' "
            "AND beneficiary_type = 'distributor' AND size(flags) > 0",
        )[0][0]
        closed_expected = _run(
            profile,
            warehouse_id,
            f"SELECT COUNT(*) FROM {lines} l JOIN {catalog}.gold.dim_pos p "
            "ON p.pos_id = l.beneficiary_id "
            f"JOIN {c}.batches b ON b.batch_id = l.batch_id WHERE l.batch_id = '{batch_id}' "
            "AND l.beneficiary_type = 'pos' AND p.closed_date >= b.reference_month "
            "AND p.closed_date <= last_day(b.reference_month)",
        )[0][0]
    except (RuntimeError, IndexError) as error:
        return [f"FALHA não consegui ler os flags: {error}"]

    unknown = sorted(set(counts) - set(ALLOWED))
    out = [
        _mark(not unknown, f"{batch_id}: só flags da SPEC (desconhecidos: {unknown or 'nenhum'})"),
        _mark(int(on_distributor or 0) == 0, f"linhas de distribuidor com flag: {on_distributor}"),
        _mark(
            int(counts.get("closed_pos") or 0) == int(closed_expected or 0),
            f"closed_pos = {counts.get('closed_pos', '0')} (esperado {closed_expected})",
        ),
    ]
    if expect_fractioning:
        found = int(counts.get("fractioning_suspect") or 0)
        out.append(_mark(found >= 3, f"fractioning_suspect = {found} (esperado >= 3)"))
    out.extend(f"info  {flag} = {counts.get(flag, '0')}" for flag in ALLOWED)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--batch-id", required=True, help="ex.: COM-2026-10-v1")
    parser.add_argument(
        "--expect-fractioning",
        action="store_true",
        help="dataset com o cenário `fractioning`: exige >= 3 PDVs com fractioning_suspect",
    )
    args = parser.parse_args(argv)
    out = check(
        args.profile,
        args.warehouse_id,
        CATALOGS[args.target],
        args.batch_id,
        args.expect_fractioning,
    )
    print("\n".join(out))
    return 1 if any(line.startswith("FALHA") for line in out) else 0


if __name__ == "__main__":
    sys.exit(main())
