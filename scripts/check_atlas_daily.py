"""Confere a última execução do job `atlas_daily` (SPEC-002 §5, task P6.7).

Critério da P6.7: a execução agendada termina antes das 08:00 (meta < 30 min). O job só roda no
workspace, então o **mantenedor** roda este script depois de uma execução das 06:00:

    uv run python scripts/check_atlas_daily.py --target dev --profile andrevidal \\
        --warehouse-id <id>

Só lê. Mostra o fim da última execução concluída (America/Sao_Paulo), a duração e a última linha de
`observability.pipeline_freshness`. Sai com 0 se terminou com SUCCESS antes das 08:00; com 1 senão.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from datetime import datetime, time
from zoneinfo import ZoneInfo

CATALOGS = {"dev": "atlas_dev", "demo": "atlas"}  # igual ao databricks.yml
TZ = ZoneInfo("America/Sao_Paulo")
DEADLINE = time(8, 0)


def finished_before_deadline(end_ms: int, deadline: time = DEADLINE) -> bool:
    """Fim da execução (epoch ms) é no mesmo dia local e antes do prazo?"""
    end = datetime.fromtimestamp(end_ms / 1000, TZ)
    return end.time() < deadline


def _cli(profile: str, args: Sequence[str], body: dict[str, object] | None = None) -> object:
    command = ["databricks", "--profile", profile, *args, "-o", "json"]
    if body is not None:
        command += ["--json", json.dumps(body)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"`databricks {' '.join(args)}` falhou: {result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    args = parser.parse_args(argv)
    catalog = CATALOGS[args.target]

    jobs = _cli(args.profile, ["jobs", "list", "--name", "atlas_daily"])
    ids = [j["job_id"] for j in jobs or [] if isinstance(j, dict)]  # type: ignore[union-attr]
    if len(ids) != 1:
        print(f"FALHA esperava 1 job atlas_daily, achei {len(ids)}")
        return 1
    runs = _cli(
        args.profile,
        ["jobs", "list-runs", "--job-id", str(ids[0]), "--completed-only", "--limit", "1"],
    )
    if not runs:
        print("FALHA nenhuma execução concluída ainda")
        return 1
    run = runs[0]  # type: ignore[index]
    state = run.get("state", {}).get("result_state")
    start_ms, end_ms = int(run["start_time"]), int(run["end_time"])
    minutes = (end_ms - start_ms) / 60000
    end_local = datetime.fromtimestamp(end_ms / 1000, TZ)
    ok = state == "SUCCESS" and finished_before_deadline(end_ms)
    print(
        f"{'ok   ' if ok else 'FALHA'} execução {run.get('run_id')}: {state}, terminou "
        f"{end_local:%Y-%m-%d %H:%M} (Brasília), duração {minutes:.1f} min (meta < 30)"
    )
    statement = (
        "SELECT CAST(run_ts_utc AS STRING), CAST(max_recharge_date AS STRING), freshness_status, "  # noqa: S608
        "CAST(dropped_ratio AS STRING), quality_status "
        f"FROM {catalog}.observability.pipeline_freshness ORDER BY run_ts_utc DESC LIMIT 1"
    )
    body = {"warehouse_id": args.warehouse_id, "statement": statement, "wait_timeout": "50s"}
    resp = _cli(args.profile, ["api", "post", "/api/2.0/sql/statements"], body)
    data = resp["result"]["data_array"] if resp else []  # type: ignore[index]
    print(f"pipeline_freshness (última linha): {data[0] if data else 'vazia'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
