"""Confere o dataset `<catalog>.eval.agent_golden_set` no Unity Catalog (SPEC-008 §3, task P9.2).

O dataset só existe no workspace, então o **mantenedor** roda este script no `dev` depois do job
`atlas_eval_sync`:

    uv run python scripts/check_agent_golden_set.py --target dev --profile andrevidal \\
        --warehouse-id <id>

Só lê. Falha (saída 1) se a tabela não existir, não tiver versão ou não tiver exatamente
tantas linhas quanto os casos de `eval/golden_set.yaml` (o job já confere ids e conteúdo).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # importável de qualquer diretório
from check_golden_set import CATALOGS, _run, load_cases


def check_counts(expected: int, actual: int, version: int | None) -> str:
    """Uma linha de relatório: `ok ...` ou `FALHA ...`."""
    if version is None:
        return "FALHA: a tabela não tem versão (DESCRIBE HISTORY vazio)"
    if actual != expected:
        return f"FALHA: {actual} linhas no dataset, o YAML tem {expected} casos"
    return f"ok    {actual} linhas (YAML: {expected} casos), versão {version}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=sorted(CATALOGS), required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda a consulta")
    args = parser.parse_args(argv)

    table = f"{CATALOGS[args.target]}.eval.agent_golden_set"
    try:
        count = _run(args.profile, args.warehouse_id, f"SELECT count(*) FROM {table}")  # noqa: S608
        history = _run(args.profile, args.warehouse_id, f"DESCRIBE HISTORY {table} LIMIT 1")
    except RuntimeError as error:
        print(f"FALHA: {error}")
        return 1
    version = int(history[0][0]) if history and history[0][0] is not None else None
    line = check_counts(len(load_cases()), int(count[0][0] or 0), version)
    print(line)
    return 1 if line.startswith("FALHA") else 0


if __name__ == "__main__":
    sys.exit(main())
