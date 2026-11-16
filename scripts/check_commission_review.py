"""Confere o relatório `commission_review` de um lote (SPEC-003 §5.4, task P8.8).

Depois do deploy do bundle em `dev`, o **mantenedor** roda, só com leitura:

    uv run python scripts/check_commission_review.py --target dev \\
        --profile <perfil> --warehouse-id <id> --batch-id COM-2026-10-v1

Roda no warehouse as mesmas consultas do dashboard e do notebook
(`commission/review_sql`, restritas ao lote) e confere cada uma contra uma consulta
independente em `commission.batch_lines`: totais iguais aos do cabeçalho, uma linha de
reconciliação, top 20 ordenado e com `min(20, linhas)` linhas, linhas com flag iguais à contagem
dos totais e, se houver lote anterior, que ele é `locked` e do mês civil anterior. Depois abra o
dashboard "Atlas — Revisão de Comissão", escolha o lote e confira que os cartões e as tabelas
mostram os mesmos números. Sai com 0 ou 1.
"""

from __future__ import annotations

# ruff: noqa: S608  (SQL só com `batch_id` validado por regex; o catálogo vai no corpo da API)
import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from check_commission_draft import CATALOGS, _mark, check_batch_id

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from commission import review_report  # noqa: E402


def _run(profile: str, warehouse_id: str, catalog: str, statement: str) -> list[list[str | None]]:
    body = {
        "warehouse_id": warehouse_id,
        "statement": statement,
        "catalog": catalog,
        "schema": "commission",
        "wait_timeout": "50s",
    }
    command = [
        "databricks", "--profile", profile, "api", "post", "/api/2.0/sql/statements",
        "--json", json.dumps(body), "-o", "json",
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"{result.stderr.strip()} {result.stdout.strip()}")
    response = json.loads(result.stdout)
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(json.dumps(status))
    return list(response.get("result", {}).get("data_array", []))


def _report(stem: str, batch_id: str) -> str:
    # o mesmo corte do notebook, com o parâmetro vinculado trocado pelo literal já validado
    return review_report.batch_query(stem).replace(":batch_id", f"'{batch_id}'")


def check(profile: str, warehouse_id: str, catalog: str, batch_id: str) -> list[str]:
    check_batch_id(batch_id)

    def run(statement: str) -> list[list[str | None]]:
        return _run(profile, warehouse_id, catalog, statement)

    try:
        totals = run(
            "SELECT total_pos_brl, total_distributor_brl, pos_lines, distributor_lines, "
            f"flagged_lines, reconciliation_status FROM ({review_report.load_sql('totals')}) "
            f"WHERE batch_id = '{batch_id}'"
        )
        independent = run(
            "SELECT "
            "COALESCE(SUM(CASE WHEN beneficiary_type = 'pos' THEN commission_brl END), 0), "
            "COALESCE(SUM(CASE WHEN beneficiary_type = 'distributor' THEN commission_brl END), 0), "
            "COUNT_IF(beneficiary_type = 'pos'), COUNT_IF(beneficiary_type = 'distributor'), "
            f"COUNT_IF(size(flags) > 0) FROM batch_lines WHERE batch_id = '{batch_id}'"
        )
        top20 = run(f"SELECT rnk, commission_brl FROM ({_report('top20', batch_id)})")
        flagged = run(f"SELECT COUNT(*) FROM ({_report('flagged', batch_id)})")
        counts = run(f"SELECT flag, lines FROM ({_report('flag_counts', batch_id)})")
        previous = run(f"SELECT previous_batch_id FROM ({_report('previous_totals', batch_id)})")
        previous_pos = run(f"SELECT COUNT(*) FROM ({_report('previous_pos', batch_id)})")
        header = run(f"SELECT reference_month FROM batches WHERE batch_id = '{batch_id}'")
        prev_id = previous[0][0] if previous else None
        prev_info = (
            run(
                "SELECT status, reference_month, add_months(reference_month, 1) FROM batches "
                f"WHERE batch_id = '{prev_id}'"
            )
            if prev_id
            else []
        )
    except (RuntimeError, IndexError) as error:
        return [f"FALHA não consegui rodar o relatório: {error}"]

    out: list[str] = []
    out.append(_mark(len(totals) == 1, f"{batch_id}: totais devolvem 1 linha ({len(totals)})"))
    if len(totals) != 1 or not independent:
        return [*out, "FALHA lote sem cabeçalho no relatório"]
    t, i = totals[0], independent[0]
    out.append(_mark(t[0] == i[0], f"total PDV {t[0]} = soma das linhas {i[0]}"))
    out.append(_mark(t[1] == i[1], f"total distribuidor {t[1]} = soma das linhas {i[1]}"))
    out.append(_mark(t[2:5] == i[2:5], f"contagens {t[2:5]} = {i[2:5]}"))
    out.append(_mark(t[5] is not None, f"reconciliação no relatório: {t[5]}"))

    pos_lines = int(t[2] or 0) + int(t[3] or 0)
    ranks = [int(r[0] or 0) for r in top20]
    amounts = [float(r[1] or 0) for r in top20]
    out.append(
        _mark(
            len(top20) == min(20, pos_lines),
            f"top 20: {len(top20)} linhas (esperado {min(20, pos_lines)})",
        )
    )
    out.append(
        _mark(
            ranks == list(range(1, len(top20) + 1)) and amounts == sorted(amounts, reverse=True),
            "top 20 ordenado por comissão, ranks 1..N",
        )
    )
    out.append(
        _mark(
            int(flagged[0][0] or 0) == int(t[4] or 0),
            f"linhas com flag: {flagged[0][0]} = {t[4]}",
        )
    )
    out.extend(f"info  {flag} = {n}" for flag, n in sorted((c[0] or "", c[1]) for c in counts))

    if prev_id:
        status, month, expected = prev_info[0] if prev_info else (None, None, None)
        out.append(
            _mark(
                status == "locked" and expected == header[0][0],
                f"lote anterior {prev_id}: {status}, mês {month}",
            )
        )
        out.append(f"info  PDVs na comparação (máx. 50) = {previous_pos[0][0]}")
    else:
        out.append(
            _mark(
                int(previous_pos[0][0] or 0) == 0,
                "sem lote locked no mês anterior: comparação vazia (esperado)",
            )
        )
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
