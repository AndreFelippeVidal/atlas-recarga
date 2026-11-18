"""Spike P12.10: latência de leitura do Lakebase (synced table) para o mapa de UFs.

Roda depois de a synced table estar `ONLINE` (runbook em docs/spikes/P12.10-dashboard-latency.md).
O `psycopg` não é dependência do projeto; use `--with` para não alterar o `pyproject.toml`:

    uv run --with "psycopg[binary]" python scripts/spike_lakebase_read.py \
        --profile andrevidal --endpoint projects/<P>/branches/<B>/endpoints/<E> \
        --user <usuário do Postgres> --table semantic.spike_map_agg [--month 2026-10]

Mede 3 coisas, em ms: conexão nova (token + TLS), 1ª leitura e leituras seguintes. O token e o
host vêm da CLI; nada é gravado em disco.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spike_dashboard_latency import format_row

TABLE_RE = re.compile(r"[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*")


def cli_json(profile: str, *args: str) -> dict[str, object]:
    out = subprocess.run(  # noqa: S603
        ["databricks", "postgres", *args, "--profile", profile, "-o", "json"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    parsed: dict[str, object] = json.loads(out)
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--endpoint", required=True, help="projects/<P>/branches/<B>/endpoints/<E>")
    parser.add_argument("--user", required=True, help="papel do Postgres")
    parser.add_argument("--table", default="semantic.spike_map_agg")
    parser.add_argument("--month", default="2026-10")
    parser.add_argument("--database", default="databricks_postgres")
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args(argv)
    if not TABLE_RE.fullmatch(args.table):
        print("--table deve ser schema.tabela")
        return 1

    import psycopg

    host = str(cli_json(args.profile, "get-endpoint", args.endpoint)["status"]["hosts"]["host"])  # type: ignore[index]
    token = str(cli_json(args.profile, "generate-database-credential", args.endpoint)["token"])

    start = time.perf_counter()
    conn = psycopg.connect(
        host=host, dbname=args.database, user=args.user, password=token, sslmode="require"
    )
    connect_s = time.perf_counter() - start
    sql = (
        f"SELECT uf, gross_revenue FROM {args.table} "  # noqa: S608
        "WHERE level = 'uf' AND recharge_month = %s"
    )
    samples: list[float] = []
    with conn, conn.cursor() as cur:
        for _ in range(args.repeat + 1):
            t0 = time.perf_counter()
            cur.execute(sql, (f"{args.month}-01",))
            rows = cur.fetchall()
            samples.append(time.perf_counter() - t0)
    print(f"conexão nova: {connect_s * 1000:.0f} ms; {len(rows)} UFs por leitura\n")
    print("| consulta | n | mín ms | p50 ms | p95 ms | máx ms |")
    print("|---|---|---|---|---|---|")
    print(format_row("1ª leitura (pode acordar o compute)", samples[:1]))
    print(format_row("UFs no Lakebase (leituras seguintes)", samples[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
