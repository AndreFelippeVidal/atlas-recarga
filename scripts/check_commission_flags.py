"""Confere os flags de revisão do lote de comissão (SPEC-003 §5 e §8, task P8.5).

Depois do job `atlas_commission_draft` (que agora inclui `flag_draft`), o **mantenedor** roda,
só com leitura:

    uv run python scripts/check_commission_flags.py --target dev \\
        --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-v1

Confere em `commission.batch_lines`: só valores do conjunto de flags da SPEC; nenhum flag em
linha de distribuidor; `closed_pos` = PDVs com linha e `closed_date` no mês; e
`fractioning_suspect` = PDVs com rajada (> 20 recargas de R$ 10 do mesmo assinante em < 10 min)
no mês do lote, contados por uma consulta independente. O cenário `fractioning` espalha as 3
rajadas por meses diferentes, então cada lote só vê as do seu mês (critério 3 da SPEC-003 §8).
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
        burst_expected = _run(
            profile,
            warehouse_id,
            f"""WITH b AS (SELECT reference_month AS ref FROM {c}.batches
                          WHERE batch_id = '{batch_id}'),
            f AS (SELECT x.pos_id, x.subscriber_id, x.recharge_ts_utc
                  FROM {catalog}.gold.fct_recharges x JOIN b ON x.recharge_month = b.ref
                  WHERE x.status = 'approved' AND x.amount_brl = 10),
            cand AS (SELECT pos_id, subscriber_id FROM f
                     GROUP BY pos_id, subscriber_id HAVING COUNT(*) >= 21)
            SELECT COUNT(DISTINCT a.pos_id) FROM (
              SELECT f1.pos_id, f1.subscriber_id, f1.recharge_ts_utc,
                     (SELECT COUNT(*) FROM f f2
                      WHERE f2.pos_id = f1.pos_id AND f2.subscriber_id = f1.subscriber_id
                        AND f2.recharge_ts_utc >= f1.recharge_ts_utc
                        AND f2.recharge_ts_utc < f1.recharge_ts_utc + INTERVAL 10 MINUTES) AS n
              FROM f f1 JOIN cand USING (pos_id, subscriber_id)) a
            WHERE a.n >= 21""",
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
    found = int(counts.get("fractioning_suspect") or 0)
    out.append(
        _mark(
            found == int(burst_expected or 0),
            f"fractioning_suspect = {found} (esperado {burst_expected}: PDVs com rajada no mês)",
        )
    )
    out.extend(f"info  {flag} = {counts.get(flag, '0')}" for flag in ALLOWED)
    return out


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
