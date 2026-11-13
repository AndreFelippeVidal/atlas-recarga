"""Confere o Genie Space "Atlas Recarga" (SPEC-004 §8, critério 5, task P7.5).

Critério 5: ao perguntar "qual a receita por DDD em outubro?", o Genie usa `ddd` e
`gross_revenue` de `mv_recharges`. O Space só existe no workspace, então o **mantenedor** roda
este script depois do `databricks bundle deploy`:

    uv run python scripts/check_genie_space.py --target dev --profile <perfil>

Faz uma pergunta pela API de conversa (a CLI espera a resposta) e inspeciona o SQL que o Genie
gerou. Sai com 0 se o SQL consulta `mv_recharges`, agrupa por `ddd`, usa `MEASURE(...gross_revenue)`
e não toca em gold, silver, bronze nem commission; sai com 1 caso contrário ou se o Space não for
encontrado. A resposta do Genie não é determinística: se falhar, rode de novo e leia o SQL impresso.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Sequence
from typing import Any

SPACE_TITLE = "Atlas Recarga"
QUESTION = "qual a receita por DDD em outubro?"
FORBIDDEN_SCHEMAS = ("gold", "silver", "bronze", "commission")


def evaluate(sql: str | None) -> list[str]:
    """Uma linha por verificação sobre o SQL gerado: `ok` ou `FALHA`."""
    if not sql:
        return ["FALHA o Genie não devolveu SQL"]
    text = sql.lower()
    groups_by_ddd = re.search(r"group\s+by[^;]*\bddd\b", text) is not None
    uses_measure = re.search(r"measure\s*\(\s*([`\w]+\.)?`?gross_revenue`?\s*\)", text) is not None
    leaks = [s for s in FORBIDDEN_SCHEMAS if re.search(rf"\b{s}\.", text)]
    checks = [
        ("consulta mv_recharges", "mv_recharges" in text),
        ("agrupa por ddd", groups_by_ddd),
        ("usa MEASURE(gross_revenue)", uses_measure),
        ("não lê gold/silver/bronze/commission" + (f" (leu {leaks})" if leaks else ""), not leaks),
    ]
    return [f"{'ok   ' if passed else 'FALHA'} {label}" for label, passed in checks]


def extract_sql(message: dict[str, Any]) -> str | None:
    """O SQL do primeiro anexo de consulta da mensagem do Genie."""
    for attachment in message.get("attachments") or []:
        query = attachment.get("query")
        if query and query.get("query"):
            return str(query["query"])
    return None


def find_space_id(spaces_response: Any, title: str = SPACE_TITLE) -> str | None:
    """Id do único Space cujo título contém `title` (o modo dev pode prefixar o título).

    Devolve None se não houver nenhum; levanta erro se houver mais de um (dev e demo juntos).
    """
    spaces = spaces_response
    if isinstance(spaces_response, dict):
        spaces = spaces_response.get("spaces", [])
    found = [str(s["space_id"]) for s in spaces or [] if title in (s.get("title") or "")]
    if len(found) > 1:
        raise RuntimeError(f"{len(found)} Spaces com '{title}'; apague o que não é deste target")
    return found[0] if found else None


def _cli(profile: str, *args: str) -> Any:
    command = ["databricks", "--profile", profile, *args, "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:2])} falhou: {result.stderr.strip()}")
    return json.loads(result.stdout)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--target", choices=["dev", "demo"], required=True)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    args = parser.parse_args(argv)

    space_id = find_space_id(_cli(args.profile, "genie", "list-spaces"))
    if space_id is None:
        print(f"FALHA Space '{SPACE_TITLE}' não encontrado; rode o bundle deploy -t {args.target}")
        return 1
    message = _cli(args.profile, "genie", "start-conversation", space_id, QUESTION)
    sql = extract_sql(message)
    print(f"Pergunta: {QUESTION}\nSQL gerado:\n{sql}\n")
    lines = evaluate(sql)
    print("\n".join(lines))
    return 1 if any(line.startswith("FALHA") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
