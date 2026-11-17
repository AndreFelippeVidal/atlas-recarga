"""Tools do agente: lista fechada da SPEC-005 §3 (`ask_genie` + 3 UC functions), P10.3.

A lógica pura (nomes, URL, polling) não importa langchain nem mlflow e é testada no CI. Os
`build_*` importam o que é pesado só ao rodar (no App).

Nomes dos spans: o scorer `read_only_tools` (SPEC-008) aceita só `ask_genie`, `fn_list_metrics`,
`fn_metric_by_region` e `fn_compare_months`; por isso as tools são renomeadas para esses nomes.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from agent_server.config import UC_FUNCTIONS, AgentConfig

GENIE_TIMEOUT_SECONDS = 30.0  # SPEC-005 §6: Genie com timeout > 30s cai para a UC function
GENIE_POLL_INTERVAL_SECONDS = 2.0
_TERMINAL_STATUS = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_QUERY_HINTS = ("query", "ask")
_POLL_HINTS = ("poll",)


class GenieUnavailableError(RuntimeError):
    """Genie fora do ar, com falha ou com timeout; o agente tenta a UC function equivalente."""


def short_tool_name(name: str) -> str:
    """`atlas_dev__semantic__fn_x` ou `atlas_dev.semantic.fn_x` viram `fn_x`."""
    return name.replace("__", ".").rsplit(".", 1)[-1]


def genie_mcp_url(host: str, space_id: str) -> str:
    """Genie Agent MCP: restrito a um Space (não passa pelo Unity Gateway; SPEC-005 §3)."""
    return f"{host.rstrip('/')}/api/2.0/mcp/genie/{space_id}"


def pick_tool(names: list[str], hints: tuple[str, ...]) -> str:
    """O nome da tool do MCP que contém uma das dicas; erro claro se não houver."""
    for name in names:
        if any(h in name.lower() for h in hints):
            return name
    raise GenieUnavailableError(f"o MCP do Genie não expõe uma tool com {hints}: {names}")


def status_of(text: str) -> str | None:
    """`status` de uma resposta JSON do MCP; `None` se não for JSON ou não tiver status."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    value = data.get("status") if isinstance(data, dict) else None
    return value.upper() if isinstance(value, str) else None


def ask_with_polling(
    call: Callable[[str, dict[str, Any]], str],
    tool_names: list[str],
    question: str,
    *,
    timeout: float = GENIE_TIMEOUT_SECONDS,
    interval: float = GENIE_POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Faz a pergunta e espera a resposta final do Genie, com o timeout do §6."""
    started = clock()
    text = call(pick_tool(tool_names, _QUERY_HINTS), {"query": question})
    status = status_of(text)
    if status is None or status == "COMPLETED":
        return text
    poll = pick_tool(tool_names, _POLL_HINTS)
    payload = json.loads(text)
    # A resposta traz camelCase (`conversationId`); a tool de polling pede snake_case.
    ids = {
        "conversation_id": payload.get("conversationId"),
        "message_id": payload.get("messageId"),
    }
    if not all(ids.values()):
        raise GenieUnavailableError("resposta do Genie sem conversationId/messageId")
    while status not in _TERMINAL_STATUS:
        if clock() - started > timeout:
            raise GenieUnavailableError(f"Genie sem resposta em {timeout:.0f}s")
        sleep(interval)
        text = call(poll, ids)
        status = status_of(text)
        if status is None:
            return text
    if status != "COMPLETED":
        raise GenieUnavailableError(f"Genie terminou com status {status}")
    return text


def build_ask_genie(config: AgentConfig, workspace_client: Any) -> Any:
    """A tool `ask_genie`: uma pergunta em PT-BR ao Space, com a espera do MCP embutida."""
    from databricks_mcp import DatabricksMCPClient
    from langchain_core.tools import tool

    if config.genie_space_id is None:
        raise RuntimeError("ATLAS_GENIE_SPACE_ID não definido (recurso genie-space do App)")
    client = DatabricksMCPClient(
        server_url=genie_mcp_url(workspace_client.config.host, config.genie_space_id),
        workspace_client=workspace_client,
    )
    names = [t.name for t in client.list_tools()]

    def call(name: str, arguments: dict[str, Any]) -> str:
        result = client.call_tool(name, arguments)
        return "\n".join(c.text for c in result.content if getattr(c, "text", None))

    @tool("ask_genie")  # type: ignore[untyped-decorator]
    def ask_genie(question: str) -> str:
        """Pergunta analítica aberta, em português, sobre as metric views de recargas.
        Use quando as funções fn_* não cobrirem a pergunta."""
        return ask_with_polling(call, names, question)

    return ask_genie


def build_uc_tools(config: AgentConfig, workspace_client: Any) -> list[Any]:
    """As 3 UC functions, só da lista fechada, com o nome curto que o scorer espera."""
    from databricks_langchain import DatabricksFunctionClient, UCFunctionToolkit

    if config.warehouse_id is None:
        raise RuntimeError("DATABRICKS_WAREHOUSE_ID não definido (recurso sql-warehouse do App)")
    # As funções são SQL: rodam pelo warehouse (Statement Execution API). O modo serverless
    # padrão exigiria o databricks-connect, que o App não instala.
    toolkit = UCFunctionToolkit(
        function_names=config.uc_function_names(),
        client=DatabricksFunctionClient(client=workspace_client, warehouse_id=config.warehouse_id),
    )
    tools = list(toolkit.tools)
    for t in tools:
        t.name = short_tool_name(t.name)
    unexpected = {t.name for t in tools} - set(UC_FUNCTIONS)
    if unexpected or len(tools) != len(UC_FUNCTIONS):
        raise RuntimeError(f"UC functions fora da lista fechada: {sorted(unexpected)}")
    return tools


def build_tools(config: AgentConfig, workspace_client: Any) -> list[Any]:
    return [build_ask_genie(config, workspace_client), *build_uc_tools(config, workspace_client)]
