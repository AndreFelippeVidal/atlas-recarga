"""Mede o p95 dos municípios de uma UF no App `atlas-web` implantado (P12.8, SPEC-007 §6).

O mantenedor roda isto no `dev`, **logo depois** de um deploy ou `databricks apps start` (o cache da
API está frio para os municípios: o aquecimento da subida só cobre meses, KPIs, regiões e UFs). A
1ª chamada de cada (UF, medida) é um cache frio de API; o script só conta essas. O que fica de fora:
a rede do navegador e o peso da geometria `geo/mun/<UF>.json`, que o navegador guarda em cache.

    uv run python scripts/measure_web_p95.py --profile andrevidal --url https://<app>.databricksapps.com

A autenticação usa o SDK do Databricks (OAuth do perfil); nenhum token é impresso. Sai com código 0
quando o p95 fica abaixo de 3 s, 1 se passar ou houver falhas e 2 se o cache estava quente.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

UFS = tuple(
    [
        "AC",
        "AL",
        "AM",
        "AP",
        "BA",
        "CE",
        "DF",
        "ES",
        "GO",
        "MA",
        "MG",
        "MS",
        "MT",
        "PA",
        "PB",
        "PE",
        "PI",
        "PR",
        "RJ",
        "RN",
        "RO",
        "RR",
        "RS",
        "SC",
        "SE",
        "SP",
        "TO",
    ]
)
MEASURES = (
    "gross_revenue",
    "recharge_count",
    "avg_ticket",
    "active_pos",
    "mom_change",
)  # as 5 de map_data
LIMIT_MS = 3000.0
WARM_P50_MS = 150.0  # abaixo disso as respostas vieram do cache de 10 min do App, não do warehouse


def percentile(samples: Sequence[float], q: float) -> float:
    """Percentil por posto mais próximo (sem interpolação)."""
    if not samples:
        raise ValueError("sem amostras")
    ordered = sorted(samples)
    return ordered[max(1, math.ceil(q / 100 * len(ordered))) - 1]


def summarize(samples_ms: Sequence[float]) -> dict[str, float]:
    return {
        "n": float(len(samples_ms)),
        "min": min(samples_ms),
        "p50": percentile(samples_ms, 50),
        "p95": percentile(samples_ms, 95),
        "max": max(samples_ms),
    }


def measure(
    get: Callable[[str, dict[str, str]], tuple[int, float]],
    month: str,
    ufs: Sequence[str] = UFS,
    measures: Sequence[str] = MEASURES,
) -> tuple[list[float], list[str]]:
    """Uma chamada fria por (UF, medida). Devolve as latências (ms) e as falhas."""
    samples: list[float] = []
    failures: list[str] = []
    for measure_name in measures:
        for uf in ufs:
            status, ms = get(
                "/api/map/municipality", {"month": month, "measure": measure_name, "uf": uf}
            )
            if status != 200:
                failures.append(f"{measure_name}/{uf}: HTTP {status}")
            else:
                samples.append(ms)
    return samples, failures


Get = Callable[[str, dict[str, str]], tuple[int, float]]


def _client(base_url: str, profile: str) -> tuple[Get, Callable[[str], Any]]:
    import requests
    from databricks.sdk.core import Config

    cfg = Config(profile=profile)
    session = requests.Session()

    def get(path: str, params: dict[str, str]) -> tuple[int, float]:
        start = time.perf_counter()
        resp = session.get(base_url + path, params=params, headers=cfg.authenticate(), timeout=60)
        return resp.status_code, (time.perf_counter() - start) * 1000

    def get_json(path: str) -> Any:
        resp = session.get(base_url + path, headers=cfg.authenticate(), timeout=60)
        resp.raise_for_status()
        return resp.json()

    return get, get_json


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="URL do App atlas-web (sem barra final)")
    parser.add_argument("--profile", required=True, help="perfil do Databricks CLI")
    parser.add_argument("--month", default=None, help="YYYY-MM (padrão: o mais recente)")
    args = parser.parse_args(argv)

    get, get_json = _client(args.url.rstrip("/"), args.profile)
    print(f"health: {get_json('/api/health')}")
    month = args.month or get_json("/api/months")["months"][0]
    samples, failures = measure(get, month)
    if failures:
        print("falhas:\n  " + "\n  ".join(failures))
    if not samples:
        return 1
    stats = summarize(samples)
    print(f"\nmês {month}; 1 chamada fria por (UF, medida)\n")
    print("| endpoint | n | mín ms | p50 ms | p95 ms | máx ms |")
    print("|---|---|---|---|---|---|")
    print(
        f"| /api/map/municipality | {stats['n']:.0f} | {stats['min']:.0f} | {stats['p50']:.0f} "
        f"| {stats['p95']:.0f} | {stats['max']:.0f} |"
    )
    if stats["p50"] < WARM_P50_MS:
        print(
            f"\nAVISO: p50 de {stats['p50']:.0f} ms (< {WARM_P50_MS:.0f} ms): o cache de API "
            "parece quente (rodou duas vezes em 10 min ou alguém usou o dashboard). Reinicie o App "
            "(`databricks apps stop` e `start`) e rode de novo; esta medição não vale."
        )
        return 2
    ok = stats["p95"] < LIMIT_MS and not failures
    print(f"\np95 < {LIMIT_MS:.0f} ms e sem falhas: {'sim' if ok else 'NÃO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
