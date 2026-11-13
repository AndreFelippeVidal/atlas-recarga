"""Confere o rascunho do lote de comissão (SPEC-003 §2 a §4, task P8.3).

O lote só existe no workspace, então o **mantenedor** roda este script depois do job:

    databricks bundle deploy -t dev --profile andrevidal
    databricks bundle run atlas_commission_draft -t dev --profile andrevidal
    uv run python scripts/check_commission_draft.py --target dev --profile andrevidal \\
        --warehouse-id <id> --batch-id COM-2026-10-v1

Confere, só com leitura:
1. o lote existe, `version = 1`, `status = 'draft'`, `demo_mode = false`, com a versão do gold;
2. `total_pos_brl` e `total_distributor_brl` = soma das linhas (já arredondadas);
3. base dos PDVs = volume aprovado do mês em `gold.agg_pos_month`; distribuidores = PDVs;
4. sem linha com base <= 0; faixa (pela base), taxa e comissão (HALF_EVEN) conforme a SPEC-003 §2;
5. exatamente 1 evento `NULL -> draft` por `system` em `batch_events`.

A reconciliação independente em SQL é a P8.4; aqui só há sanidade. Sai com 0 ou 1.
"""

from __future__ import annotations

# ruff: noqa: S608  (SQL só com `catalog` de CATALOGS e `batch_id` validado por regex)
import argparse
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
_BATCH_ID = re.compile(r"^COM-\d{4}-(0[1-9]|1[0-2])-v[1-9]\d*$")
TIER_FLOORS = {"bronze": "0", "silver": "5000.00", "gold": "20000.00", "diamond": "50000.00"}
TIER_RATES = {"bronze": "0.0200", "silver": "0.0300", "gold": "0.0400", "diamond": "0.0500"}


def _run(profile: str, warehouse_id: str, statement: str) -> list[list[str | None]]:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    command = [
        "databricks",
        "--profile",
        profile,
        "api",
        "post",
        "/api/2.0/sql/statements",
        "--json",
        json.dumps(body),
        "-o",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"{result.stderr.strip()} {result.stdout.strip()}")
    response = json.loads(result.stdout)
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(json.dumps(status))
    return list(response.get("result", {}).get("data_array", []))


def check_batch_id(value: str) -> str:
    if not _BATCH_ID.fullmatch(value):
        raise ValueError(f"batch_id inválido: {value!r}")
    return value


def _sum(column: str, kind: str) -> str:
    """Soma por tipo de beneficiário, sempre com 2 casas (compara texto com texto)."""
    return (
        f"CAST(COALESCE(SUM(CASE WHEN beneficiary_type = '{kind}' THEN {column} END), 0) "
        "AS DECIMAL(24,2))"
    )


def queries(catalog: str, batch_id: str) -> dict[str, str]:
    """Consultas de leitura; `batch_id` e `catalog` já validados, nada de texto livre."""
    check_batch_id(batch_id)
    c = f"{catalog}.commission"
    lines = f"{c}.batch_lines WHERE batch_id = '{batch_id}'"
    rate_by_tier = " ".join(f"WHEN '{t}' THEN {r}" for t, r in TIER_RATES.items())
    tier_by_base = (
        "CASE WHEN base_amount_brl >= 50000.00 THEN 'diamond' "
        "WHEN base_amount_brl >= 20000.00 THEN 'gold' "
        "WHEN base_amount_brl >= 5000.00 THEN 'silver' ELSE 'bronze' END"
    )
    bad_pos = (
        "beneficiary_type = 'pos' AND (tier IS NULL OR tier != "
        f"{tier_by_base} OR rate != CASE tier {rate_by_tier} END)"
    )
    bad_distributor = "beneficiary_type = 'distributor' AND (tier IS NOT NULL OR rate != 0.0300)"
    return {
        "header": (
            "SELECT version, status, demo_mode, source_snapshot_version IS NOT NULL, "
            "CAST(total_pos_brl AS DECIMAL(24,2)), CAST(total_distributor_brl AS DECIMAL(24,2)), "
            f"CAST(reference_month AS STRING) FROM {c}.batches WHERE batch_id = '{batch_id}'"
        ),
        "sums": (
            f"SELECT {_sum('commission_brl', 'pos')}, {_sum('commission_brl', 'distributor')}, "
            f"{_sum('base_amount_brl', 'pos')}, {_sum('base_amount_brl', 'distributor')}, "
            f"COUNT(*) FROM {lines}"
        ),
        "gold_volume": (
            "SELECT CAST(COALESCE(SUM(a.approved_amount_brl), 0) AS DECIMAL(24,2)) "
            f"FROM {catalog}.gold.agg_pos_month a JOIN {c}.batches b "
            f"ON a.recharge_month = b.reference_month WHERE b.batch_id = '{batch_id}'"
        ),
        "bad_lines": (
            f"SELECT COUNT(*) FROM {lines} AND (base_amount_brl <= 0 "
            "OR commission_brl != CAST(BROUND(base_amount_brl * rate, 2) AS DECIMAL(14,2)) "
            f"OR ({bad_pos}) OR ({bad_distributor}))"
        ),
        "events": (
            f"SELECT COUNT(*) FROM {c}.batch_events WHERE batch_id = '{batch_id}' "
            "AND from_status IS NULL AND to_status = 'draft' AND role = 'system'"
        ),
        "events_total": f"SELECT COUNT(*) FROM {c}.batch_events WHERE batch_id = '{batch_id}'",
    }


def _mark(ok: bool, text: str) -> str:
    return f"{'ok   ' if ok else 'FALHA'} {text}"


def check(profile: str, warehouse_id: str, catalog: str, batch_id: str) -> list[str]:
    def one(statement: str) -> list[str | None]:
        rows = _run(profile, warehouse_id, statement)
        return rows[0] if rows else []

    sql = queries(catalog, batch_id)
    try:
        header = one(sql["header"])
        if not header:
            return [f"FALHA {batch_id} não existe (o job atlas_commission_draft rodou?)"]
        version, status, demo, has_snapshot, total_pos, total_dist, month = header
        sums = one(sql["sums"])
        gold = one(sql["gold_volume"])
        bad = one(sql["bad_lines"])
        events = one(sql["events"])
        events_total = one(sql["events_total"])
    except RuntimeError as error:
        return [f"FALHA não consegui ler o lote: {error}"]

    commission_pos, commission_dist, base_pos, base_dist, count = sums
    out = [
        _mark(
            version == "1" and status == "draft", f"{batch_id}: version={version} status={status}"
        ),
        _mark(demo == "false", f"demo_mode = {demo}"),
        _mark(has_snapshot == "true", "source_snapshot_version preenchida"),
        _mark(
            total_pos == commission_pos and total_dist == commission_dist,
            f"totais = soma das linhas (PDV {total_pos}, distribuidor {total_dist})",
        ),
        _mark(
            base_pos == gold[0],
            f"base dos PDVs {base_pos} = volume aprovado de {month} no gold {gold[0]}",
        ),
        _mark(base_dist == base_pos, f"base dos distribuidores {base_dist} = base dos PDVs"),
        _mark(bad[0] == "0", f"linhas fora da regra (base, faixa, taxa, centavos): {bad[0]}"),
        _mark(count not in (None, "0"), f"{count} linhas no lote"),
        _mark(events[0] == "1" and events_total[0] == "1", "1 evento NULL -> draft por system"),
    ]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda as consultas")
    parser.add_argument("--batch-id", required=True, help="ex.: COM-2026-10-v1")
    args = parser.parse_args(argv)

    lines = check(args.profile, args.warehouse_id, CATALOGS[args.target], args.batch_id)
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
