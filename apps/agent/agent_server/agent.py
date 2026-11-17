"""Agente `agent-atlas` (SPEC-005). P10.3: tools da lista fechada; LLM pelo Unity Gateway."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from functools import lru_cache

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_langchain import ChatDatabricks
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain.messages import ToolMessage
from mlflow.genai.agent_server import get_request_headers, invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    create_text_output_item,
    to_chat_completions_input,
)

from agent_server.config import AgentConfig, load_config
from agent_server.guardrails import (
    RATE_LIMIT_MESSAGE,
    RATE_LIMITED_ERROR_TYPE,
    guard_event,
    is_rate_limited,
)
from agent_server.prompts import load_prompt
from agent_server.tools import build_tools
from agent_server.utils import (
    get_session_id,
    get_user_workspace_client,
    process_agent_astream_events,
)

logger = logging.getLogger(__name__)
mlflow.langchain.autolog()
logging.getLogger("mlflow.utils.autologging_utils").setLevel(logging.ERROR)

USER_HEADERS = ("x-forwarded-email", "x-forwarded-preferred-username", "x-forwarded-user")
CONFIG = load_config()  # falha no start se ATLAS_* for inválida

SYSTEM_PROMPT = load_prompt(CONFIG.prompt_version)  # falha no start se a versão não existir


def build_llm(config: AgentConfig) -> ChatDatabricks:
    """Chama o model service de três partes pelo Unity Gateway (nunca o endpoint legado)."""
    extra = {"extra_headers": config.request_tags_headers()} if config.send_request_tags else None
    return ChatDatabricks(model=config.llm_service, use_ai_gateway=True, extra_params=extra)


@lru_cache(maxsize=1)
def _tools() -> list:
    # Lista fechada (SPEC-005 §3), com a identidade do service principal do App. Cache: o
    # list_tools do MCP é uma ida ao workspace e usa asyncio.run por dentro: chame numa thread
    # (`asyncio.to_thread`), nunca de dentro do event loop do handler.
    from langchain_core.tools import tool

    @tool
    def web_search(query: str) -> str:
        """Busca na web. Chame SEMPRE esta tool primeiro, antes de qualquer outra e de responder."""
        return "sem resultados"

    return [*build_tools(CONFIG, WorkspaceClient()), web_search]


class ToolErrorsAsMessages(AgentMiddleware):
    """Erro de tool (argumento faltando, Genie indisponível ou com timeout) vira mensagem para o
    modelo, que corrige a chamada ou tenta a UC function equivalente (SPEC-005 §6). Sem isso a
    exceção derruba a requisição inteira."""

    @staticmethod
    def _message(request: ToolCallRequest, error: Exception) -> ToolMessage:
        logger.warning("tool %s falhou: %s", request.tool_call["name"], error)
        return ToolMessage(
            content=f"Erro ao executar a tool: {error}",
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        try:
            return handler(request)
        except Exception as error:
            return self._message(request, error)

    async def awrap_tool_call(self, request: ToolCallRequest, handler):
        try:
            return await handler(request)
        except Exception as error:
            return self._message(request, error)


def build_agent(tools: list, config: AgentConfig = CONFIG):
    return create_agent(
        model=build_llm(config),
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=[ToolErrorsAsMessages()],
    )


@lru_cache(maxsize=256)
def _user_from_token(token: str) -> str | None:
    """Quem é o dono do token OAuth do usuário (o App não repassa o e-mail em cabeçalho)."""
    try:
        return get_user_workspace_client().current_user.me().user_name
    except Exception:
        logger.warning("não consegui resolver o usuário pelo token", exc_info=False)
        return None


def _tag_trace(request: ResponsesAgentRequest) -> None:
    headers = {k.lower(): v for k, v in get_request_headers().items()}
    user = next((headers[h] for h in USER_HEADERS if headers.get(h)), None)
    if user is None and (token := headers.get("x-forwarded-access-token")):
        user = _user_from_token(token)
    if user is None:  # só os nomes, nunca os valores (tokens passam por aqui)
        logger.warning("sem identidade do usuário; cabeçalhos recebidos: %s", sorted(headers))
    metadata = {}
    if session_id := get_session_id(request):
        metadata["mlflow.trace.session"] = session_id
    mlflow.update_current_trace(tags=CONFIG.trace_tags(user), metadata=metadata)


@invoke()
async def invoke_handler(request: ResponsesAgentRequest) -> ResponsesAgentResponse:
    outputs = [
        event.item
        async for event in stream_handler(request)
        if event.type == "response.output_item.done"
    ]
    return ResponsesAgentResponse(output=outputs)


@stream()
async def stream_handler(
    request: ResponsesAgentRequest,
) -> AsyncGenerator[ResponsesAgentStreamEvent, None]:
    _tag_trace(request)
    messages = {"messages": to_chat_completions_input([i.model_dump() for i in request.input])}
    tools = await asyncio.to_thread(_tools)
    try:
        async for event in process_agent_astream_events(
            build_agent(tools).astream(input=messages, stream_mode=["updates", "messages"])
        ):
            keep, masked = guard_event(event)  # PII na saída (ADR-0021)
            if masked:
                mlflow.update_current_trace(tags={"pii_masked": "true"})
            if keep:
                yield event
    except Exception as error:
        if not is_rate_limited(error):
            raise
        # 429 do gateway (SPEC-005 §6): mensagem ao usuário e marca no trace.
        logger.warning("429 do gateway: %s", error)
        mlflow.update_current_trace(tags={"error_type": RATE_LIMITED_ERROR_TYPE})
        yield ResponsesAgentStreamEvent(
            type="response.output_item.done",
            item=create_text_output_item(RATE_LIMIT_MESSAGE, id="rate_limited"),
        )
