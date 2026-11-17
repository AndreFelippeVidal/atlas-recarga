"""Agente `agent-atlas` (SPEC-005). P10.3: tools da lista fechada; LLM pelo Unity Gateway."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from functools import lru_cache

import mlflow
from databricks.sdk import WorkspaceClient
from databricks_langchain import ChatDatabricks
from langchain.agents import create_agent
from mlflow.genai.agent_server import get_request_headers, invoke, stream
from mlflow.types.responses import (
    ResponsesAgentRequest,
    ResponsesAgentResponse,
    ResponsesAgentStreamEvent,
    to_chat_completions_input,
)

from agent_server.config import AgentConfig, load_config
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

# Provisório: o system prompt completo (Fonte:, recusa, último mês fechado) é a P10.4.
SYSTEM_PROMPT = "Você é o assistente de dados da rede de recarga Eaí? Telecom. Responda em PT-BR."


def build_llm(config: AgentConfig) -> ChatDatabricks:
    """Chama o model service de três partes pelo Unity Gateway (nunca o endpoint legado)."""
    extra = {"request_tags": config.request_tags()} if config.send_request_tags else None
    return ChatDatabricks(model=config.llm_service, use_ai_gateway=True, extra_params=extra)


@lru_cache(maxsize=1)
def _tools() -> list:
    # Lista fechada (SPEC-005 §3), com a identidade do service principal do App. Cache: o
    # list_tools do MCP é uma ida ao workspace.
    return build_tools(CONFIG, WorkspaceClient())


def build_agent(config: AgentConfig = CONFIG):
    return create_agent(model=build_llm(config), tools=_tools(), system_prompt=SYSTEM_PROMPT)


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
    async for event in process_agent_astream_events(
        build_agent().astream(input=messages, stream_mode=["updates", "messages"])
    ):
        yield event
