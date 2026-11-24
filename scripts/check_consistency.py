"""Confere que os 5 consumidores mostram o mesmo `gross_revenue` (PRD §4, task P13.2).

A meta de consistência do PRD é "o mesmo número no agente, no AI/BI e no React". Este script mede
o `gross_revenue` de um mês em cada consumidor e compara, ao centavo, com uma referência
independente (SQL direto em `gold.fct_recharges`, sem passar pela metric view):

1. AI/BI: a query do card "Receita bruta" do dashboard (`MEASURE(gross_revenue)` sobre
   `mv_recharges`, lida do `.lvdash.json` versionado e executada no warehouse);
2. Genie: a pergunta em linguagem natural, com o resultado da consulta que o Genie gerou;
3. agente: `POST /invocations` do App `agent-atlas`; o valor é extraído do texto da resposta;
4. MCP: a tool `query_metric` do App `atlas-mcp`;
5. React: `/api/kpis` do App `atlas-web` (o que o card do frontend exibe).

O mantenedor roda no `dev`, com os 3 Apps `RUNNING` (`make apps-start PROFILE=<perfil>`):

    uv run python scripts/check_consistency.py --profile <perfil> --warehouse-id <id> \\
        --catalog atlas_dev [--month 2026-10]

Sai com 0 se os 5 consumidores batem com a referência e com 1 se algum difere ou falha. O Genie e
o agente são modelos: se só um deles falhar, rode de novo e leia a resposta impressa. A conferência
visual do card no navegador não é feita aqui (a query do dataset é a mesma, mas o desenho não).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess  # a CLI do Databricks é a única coisa que chamamos
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "semantic" / "dashboards" / "atlas_visao_comercial.lvdash.json"
GROSS_WIDGET = "br-gross"
SPACE_TITLE = "Atlas Recarga"
AGENT_APP, MCP_APP, WEB_APP = "agent-atlas", "atlas-mcp", "atlas-web"
HTTP_TIMEOUT_S = 130
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_BRL = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}|\d+(?:\.\d+)?)")
MONTH_NAMES = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


@dataclass
class Reading:
    """O que um consumidor devolveu: os valores achados ou o erro que impediu a leitura."""

    name: str
    values: list[Decimal] = field(default_factory=list)
    error: str | None = None
    detail: str = ""


def parse_month(month: str) -> tuple[int, int]:
    match = _MONTH.fullmatch(month)
    if not match:
        raise ValueError(f"mês inválido: {month!r} (use YYYY-MM)")
    return int(match.group(1)), int(match.group(2))


def month_phrase(month: str) -> str:
    year, number = parse_month(month)
    return f"{MONTH_NAMES[number - 1]} de {year}"


def to_decimal(value: Any) -> Decimal | None:
    """Decimal finito a partir de string ou número; None se não for um número."""
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def extract_brl(text: str) -> list[Decimal]:
    """Os valores `R$ 4.122.460,00` (ou `R$ 4122460.00`) de um texto livre, sem duplicatas."""
    found: list[Decimal] = []
    for raw in _BRL.findall(text):
        normalized = raw.replace(".", "").replace(",", ".") if "," in raw else raw
        value = to_decimal(normalized)
        if value is not None and value not in found:
            found.append(value)
    return found


def message_text(response: Any) -> str:
    """Junta o texto dos itens `message` de uma resposta do agente (formato Responses)."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("text"), str):
                parts.append(node["text"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    items = response.get("output", []) if isinstance(response, dict) else []
    walk([i for i in items if isinstance(i, dict) and i.get("type") == "message"])
    return "\n".join(parts)


def reference_query(catalog: str, month: str) -> str:
    """Referência independente da metric view: soma aprovada no gold (como `check_web_kpis`)."""
    if not _IDENTIFIER.fullmatch(catalog):
        raise ValueError(f"catálogo inválido: {catalog!r}")
    parse_month(month)
    return (
        "SELECT CAST(SUM(amount_brl) AS STRING) "  # noqa: S608  (catálogo e mês validados acima)
        f"FROM {catalog}.gold.fct_recharges "
        f"WHERE status = 'approved' AND DATE_TRUNC('MONTH', recharge_date) = DATE'{month}-01'"
    )


def dashboard_query(dashboard: dict[str, Any], catalog: str, month: str) -> str:
    """O SQL do card "Receita bruta" do AI/BI, lido do dashboard versionado.

    Falha se o dataset não for a `mv_recharges` ou se o card não usar `MEASURE(gross_revenue)`:
    nesse caso o dashboard deixou de ler a camada semântica e a consistência não vale.
    """
    if not _IDENTIFIER.fullmatch(catalog):
        raise ValueError(f"catálogo inválido: {catalog!r}")
    parse_month(month)
    datasets = {d["name"]: d for d in dashboard.get("datasets", [])}
    expressions: list[tuple[str, str]] = []
    for page in dashboard.get("pages", []):
        for item in page.get("layout", []):
            widget = item.get("widget", {})
            if widget.get("name") != GROSS_WIDGET:
                continue
            for query in widget.get("queries", []):
                body = query.get("query", {})
                for field_ in body.get("fields", []):
                    expressions.append((body.get("datasetName", ""), field_.get("expression", "")))
    if not expressions:
        raise ValueError(f"o card '{GROSS_WIDGET}' não está no dashboard")
    dataset_name, expression = expressions[0]
    if datasets.get(dataset_name, {}).get("asset_name") != "mv_recharges":
        raise ValueError(f"o card lê o dataset {dataset_name!r}, não a mv_recharges")
    if expression.replace("`", "") != "MEASURE(gross_revenue)":
        raise ValueError(f"o card usa {expression!r}, esperado MEASURE(gross_revenue)")
    return (
        "SELECT CAST(MEASURE(gross_revenue) AS STRING) "  # noqa: S608  (validados acima)
        f"FROM {catalog}.semantic.mv_recharges "
        f"WHERE recharge_month = DATE'{month}-01'"
    )


def genie_value(result: Any) -> Decimal | None:
    """A primeira célula numérica do resultado da consulta do Genie."""
    rows = ((result or {}).get("statement_response") or {}).get("result", {}).get("data_array")
    for row in rows or []:
        for cell in row:
            value = to_decimal(cell)
            if value is not None:
                return value
    return None


def evaluate(expected: Decimal | None, readings: Sequence[Reading]) -> list[str]:
    """Uma linha por consumidor: `ok` se o valor esperado está entre os que ele devolveu."""
    if expected is None:
        return ["FALHA referência: o SQL direto no gold não devolveu um valor"]
    lines: list[str] = []
    for reading in readings:
        if reading.error:
            lines.append(f"FALHA {reading.name}: {reading.error}")
        elif expected in reading.values:
            lines.append(f"ok    {reading.name}: {expected}")
        else:
            got = ", ".join(str(v) for v in reading.values) or "nenhum valor"
            lines.append(f"FALHA {reading.name}: esperado {expected}, veio {got}")
    return lines


def read_safely(name: str, read: Callable[[], Reading]) -> Reading:
    """Um consumidor fora do ar não derruba os outros: vira uma linha `FALHA`."""
    try:
        return read()
    except Exception as exc:
        return Reading(name, error=f"{type(exc).__name__}: {exc}")


# --- acesso ao workspace (só existe no `dev`; não é coberto por testes unitários) ---


def _cli(profile: str, *args: str) -> Any:
    command = ["databricks", "--profile", profile, *args, "-o", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:2])} falhou: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _sql_value(profile: str, warehouse_id: str, statement: str) -> Decimal | None:
    body = {"warehouse_id": warehouse_id, "statement": statement, "wait_timeout": "50s"}
    response = _cli(profile, "api", "post", "/api/2.0/sql/statements", "--json", json.dumps(body))
    status = response.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(str(status.get("error", status)))
    rows = response.get("result", {}).get("data_array", [])
    return to_decimal(rows[0][0]) if rows and rows[0] else None


def _read_genie(profile: str, month: str) -> Reading:
    from check_genie_space import extract_sql, find_space_id

    space_id = find_space_id(_cli(profile, "genie", "list-spaces"), SPACE_TITLE)
    if space_id is None:
        return Reading("Genie", error=f"Space '{SPACE_TITLE}' não encontrado")
    question = f"qual a receita bruta de {month_phrase(month)}?"
    message = _cli(profile, "genie", "start-conversation", space_id, question)
    sql = extract_sql(message) or ""
    attachment = next((a for a in message.get("attachments") or [] if a.get("query")), None)
    if not attachment:
        return Reading("Genie", error="o Genie não devolveu uma consulta")
    result = _cli(
        profile,
        "genie",
        "get-message-attachment-query-result",
        space_id,
        str(message.get("conversation_id")),
        str(message.get("message_id") or message.get("id")),
        str(attachment.get("attachment_id") or attachment.get("id")),
    )
    value = genie_value(result)
    reading = Reading("Genie", values=[value] if value is not None else [], detail=sql)
    if "mv_recharges" not in sql.lower():
        reading.error = "o SQL do Genie não consulta mv_recharges"
    return reading


def _read_agent(url: str, headers: dict[str, str], month: str) -> Reading:
    import requests

    question = f"Qual a receita bruta da rede em {month_phrase(month)}?"
    response = requests.post(
        f"{url}/invocations",
        json={"input": [{"role": "user", "content": question}]},
        headers=headers,
        timeout=HTTP_TIMEOUT_S,
    )
    if response.status_code != 200:
        return Reading("agente", error=f"HTTP {response.status_code}")
    text = message_text(response.json())
    return Reading("agente", values=extract_brl(text), detail=text)


async def _call_mcp(url: str, token: str, month: str) -> Any:
    from fastmcp import Client

    arguments = {
        "view": "mv_recharges",
        "measures": ["gross_revenue"],
        "month_from": month,
        "month_to": month,
    }
    async with Client(url, auth=token) as client:
        return (await client.call_tool("query_metric", arguments)).data


def _read_mcp(url: str, token: str, month: str) -> Reading:
    data = asyncio.run(_call_mcp(f"{url}/mcp", token, month))
    rows = data.get("rows", [])
    value = to_decimal(rows[0][-1]) if rows else None
    return Reading("MCP", values=[value] if value is not None else [], detail=str(rows))


def _read_web(url: str, headers: dict[str, str], month: str) -> Reading:
    import requests

    response = requests.get(
        f"{url}/api/kpis", params={"month": month}, headers=headers, timeout=HTTP_TIMEOUT_S
    )
    if response.status_code != 200:
        return Reading("React", error=f"HTTP {response.status_code}")
    value = to_decimal(response.json()["gross_revenue"]["value"])
    return Reading("React", values=[value] if value is not None else [])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--profile", required=True, help="perfil da CLI do Databricks (explícito)")
    parser.add_argument("--warehouse-id", required=True, help="SQL warehouse que roda as queries")
    parser.add_argument("--catalog", required=True, help="catálogo do target (atlas_dev ou atlas)")
    parser.add_argument("--month", default="2026-10", help="mês YYYY-MM (padrão: 2026-10)")
    args = parser.parse_args(argv)
    parse_month(args.month)

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=args.profile)

    def headers() -> dict[str, str]:
        return dict(w.config.authenticate())  # token do usuário, só em memória (nunca impresso)

    def app_url(name: str) -> str:
        app = w.apps.get(name)
        state = app.app_status.state.value if app.app_status and app.app_status.state else None
        if state != "RUNNING" or not app.url:
            raise RuntimeError(f"{name} em {state!r} (rode `make apps-start PROFILE=...`)")
        return app.url.rstrip("/")

    expected = _sql_value(
        args.profile, args.warehouse_id, reference_query(args.catalog, args.month)
    )
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))

    def read_aibi() -> Reading:
        sql = dashboard_query(dashboard, args.catalog, args.month)
        value = _sql_value(args.profile, args.warehouse_id, sql)
        return Reading("AI/BI", values=[value] if value is not None else [], detail=sql)

    def bearer() -> str:
        scheme, _, token = headers().get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise RuntimeError("o perfil não devolveu um cabeçalho Authorization Bearer")
        return token

    readings = [
        read_safely("AI/BI", read_aibi),
        read_safely("Genie", lambda: _read_genie(args.profile, args.month)),
        read_safely("agente", lambda: _read_agent(app_url(AGENT_APP), headers(), args.month)),
        read_safely("MCP", lambda: _read_mcp(app_url(MCP_APP), bearer(), args.month)),
        read_safely("React", lambda: _read_web(app_url(WEB_APP), headers(), args.month)),
    ]
    print(f"gross_revenue de {args.month} (referência: SQL direto no gold): {expected}\n")
    for reading in readings:
        if reading.detail:
            print(f"[{reading.name}]\n{reading.detail}\n")
    lines = evaluate(expected, readings)
    print("\n".join(lines))
    failed = any(line.startswith("FALHA") for line in lines)
    print("FALHOU" if failed else "OK: os 5 consumidores mostram o mesmo gross_revenue")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
