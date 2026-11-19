"""Chat do dashboard: proxy SSE para o `agent-atlas`, com o token do usuário (ADR-0023).

O `atlas-web` não interpreta o texto, não roda LLM e não calcula métrica: repassa o que o agente
diz (com o bloco `Fonte:`). Nenhuma consulta SQL passa por aqui.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx2
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 2000
MAX_CONVERSATION_ID_CHARS = 128
TOKEN_HEADER = "x-forwarded-access-token"  # noqa: S105 (nome de cabeçalho, não é segredo)
USER_HEADERS = ("x-forwarded-email", "x-forwarded-preferred-username", "x-forwarded-user")
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@dataclass(frozen=True)
class ChatSettings:
    """Limites do contrato (ADR-0023); os testes usam valores pequenos."""

    connect_timeout_s: float = 10.0
    idle_timeout_s: float = 60.0
    total_timeout_s: float = 120.0
    ping_interval_s: float = 15.0
    rate_limit: int = 10
    rate_window_s: float = 60.0


class RateLimiter:
    """Janela deslizante por usuário, em memória (o App tem uma instância)."""

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, user: str) -> bool:
        now = self._clock()
        hits = self._hits[user]
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if not hits:
            self._hits.pop(user, None)  # não acumula usuários parados
            hits = self._hits[user]
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


def sse(event: str, data: dict[str, str]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def error_http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def parse_body(payload: Any) -> tuple[str, str | None]:
    """Valida o corpo de `POST /api/chat`. Levanta 400 INVALID_ARGUMENT."""
    if not isinstance(payload, dict):
        raise error_http(400, "INVALID_ARGUMENT", "corpo inválido")
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        raise error_http(400, "INVALID_ARGUMENT", "message não pode ser vazia")
    if len(message) > MAX_MESSAGE_CHARS:
        raise error_http(
            400, "INVALID_ARGUMENT", f"message passa de {MAX_MESSAGE_CHARS} caracteres"
        )
    conversation_id = payload.get("conversation_id")
    if conversation_id is not None and (
        not isinstance(conversation_id, str) or len(conversation_id) > MAX_CONVERSATION_ID_CHARS
    ):
        raise error_http(400, "INVALID_ARGUMENT", "conversation_id inválido")
    return message.strip(), conversation_id or None


def user_key(request: Request, token: str) -> str:
    """Quem conta no limite: o usuário repassado pelo proxy; sem ele, um hash do token."""
    for name in USER_HEADERS:
        if value := request.headers.get(name):
            return value.lower()
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _message_text(item: dict[str, Any]) -> str:
    parts = item.get("content") or []
    return "".join(
        p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)
    )


def _looks_rate_limited(text: str) -> bool:
    lowered = text.lower()
    return "429" in lowered or "rate limit" in lowered or "request_limit_exceeded" in lowered


class _Translator:
    """Linhas SSE do agente (formato Responses) -> eventos do contrato do `atlas-web`."""

    def __init__(self) -> None:
        self.final: str | None = None
        self.deltas = 0

    def feed(self, line: str) -> list[str]:
        """Devolve eventos SSE prontos, ou levanta `_Terminal` com o erro do contrato."""
        line = line.strip()
        if not line.startswith("data:"):
            return []
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            return []
        try:
            event = json.loads(raw)
        except ValueError:
            raise _Terminal("AGENT_ERROR", "resposta do agente ilegível") from None
        kind = event.get("type") if isinstance(event, dict) else None
        if kind == "response.output_text.delta":
            text = event.get("delta")
            if isinstance(text, str) and text:
                self.deltas += 1
                return [sse("delta", {"text": text})]
        elif kind == "response.output_item.done":
            item = event.get("item")
            # uma mensagem vazia não apaga a anterior
            if isinstance(item, dict) and item.get("type") == "message" and _message_text(item):
                self.final = _message_text(item)
        elif kind in ("error", "response.failed"):
            detail = json.dumps(event, ensure_ascii=False)
            if _looks_rate_limited(detail):
                raise _Terminal("RATE_LIMITED", "limite de uso do agente atingido")
            raise _Terminal("AGENT_ERROR", "o agente devolveu um erro")
        return []

    def finish(self) -> str:
        """Fim do stream do agente: `done` com o texto final, ou erro se não houve resposta."""
        if not self.final:
            raise _Terminal("AGENT_ERROR", "o agente encerrou sem resposta")
        return sse("done", {"text": self.final})


class AgentRateLimited(Exception):
    """O agente respondeu 429 antes do primeiro byte: vira o evento `error RATE_LIMITED`."""


class _Terminal(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def _pump(response: httpx2.Response, queue: asyncio.Queue[tuple[str, Any]]) -> None:
    try:
        async for line in response.aiter_lines():
            await queue.put(("line", line))
        await queue.put(("eof", None))
    except httpx2.ReadTimeout:
        await queue.put(("error", _Terminal("TIMEOUT", "o agente demorou demais para responder")))
    except httpx2.HTTPError:
        await queue.put(("error", _Terminal("AGENT_UNAVAILABLE", "o agente caiu no meio")))


async def stream_events(
    response: httpx2.Response, settings: ChatSettings, clock: Callable[[], float] = time.monotonic
) -> AsyncIterator[str]:
    """Eventos SSE do contrato; ping a cada `ping_interval_s`; sempre termina com done ou error."""
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    pump = asyncio.create_task(_pump(response, queue))
    translator = _Translator()
    started = last_byte = clock()
    try:
        while True:
            now = clock()
            wait = min(
                settings.ping_interval_s,
                settings.idle_timeout_s - (now - last_byte),
                settings.total_timeout_s - (now - started),
            )
            if wait <= 0:
                raise _Terminal("TIMEOUT", "o agente demorou demais para responder")
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=wait)
            except TimeoutError:
                now = clock()
                if (
                    now - last_byte >= settings.idle_timeout_s
                    or now - started >= settings.total_timeout_s
                ):
                    raise _Terminal("TIMEOUT", "o agente demorou demais para responder") from None
                yield ": ping\n\n"
                continue
            if kind == "error":
                raise payload
            if kind == "eof":
                yield translator.finish()
                return
            last_byte = clock()
            for out in translator.feed(payload):
                yield out
    except _Terminal as terminal:
        yield sse("error", {"code": terminal.code, "message": terminal.message})
    finally:  # inclui o cliente que fechou (botão "Parar"): fecha a conexão com o agente
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        await response.aclose()


async def open_agent_stream(
    client: httpx2.AsyncClient,
    agent_url: str,
    token: str,
    message: str,
    conversation_id: str | None,
) -> httpx2.Response:
    """Abre o stream do agente e confere o status. Falhas viram HTTP (antes do primeiro byte)."""
    body: dict[str, Any] = {
        "input": [{"role": "user", "content": message}],
        "stream": True,
    }
    if conversation_id:
        body["context"] = {"conversation_id": conversation_id}
    request = client.build_request(
        "POST",
        f"{agent_url.rstrip('/')}/invocations",
        json=body,
        headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"},
    )
    try:
        response = await client.send(request, stream=True)
    except httpx2.HTTPError:
        log.warning("agente inalcançável", exc_info=False)
        raise error_http(503, "AGENT_UNAVAILABLE", "o agente está parado ou indisponível") from None
    status = response.status_code
    if status < 400 and not response.is_redirect:
        return response
    await response.aclose()
    if status == 429:
        raise AgentRateLimited
    if status in (401, 403) or response.is_redirect:  # o proxy do App manda o sem acesso ao login
        raise error_http(403, "PERMISSION_DENIED", "sem acesso ao agente")
    log.warning("agente respondeu %s", status)
    raise error_http(503, "AGENT_UNAVAILABLE", "o agente está parado ou indisponível")


def immediate_error(code: str, message: str) -> StreamingResponse:
    async def one() -> AsyncIterator[str]:
        yield sse("error", {"code": code, "message": message})

    return StreamingResponse(one(), media_type="text/event-stream", headers=SSE_HEADERS)
