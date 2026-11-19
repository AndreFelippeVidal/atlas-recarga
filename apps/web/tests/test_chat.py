"""Contrato do `POST /api/chat` (ADR-0023) com o agente simulado. Nenhum SQL passa por aqui."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx2
import pytest
from atlas_web.app import create_app
from atlas_web.chat import MAX_MESSAGE_CHARS, ChatSettings, RateLimiter
from fastapi.testclient import TestClient

HEADERS = {"x-forwarded-access-token": "user-token", "x-forwarded-email": "ana@exemplo.com"}
FONTE = "Fonte: semantic.mv_recharges · gross_revenue · recharge_month = 2026-10"
ANSWER = f"A receita de outubro foi de R$ 4.122.460,00.\n{FONTE}"


def data(obj: dict[str, Any]) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def delta(text: str) -> str:
    return data({"type": "response.output_text.delta", "item_id": "m1", "delta": text})


def message_done(text: str) -> str:
    item = {"type": "message", "content": [{"type": "output_text", "text": text}]}
    return data({"type": "response.output_item.done", "item": item})


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLAS_AGENT_URL", "https://agent.example")


class Agent:
    """Agente simulado: guarda as chamadas e devolve o que o teste mandar."""

    def __init__(self, chunks: Callable[[], AsyncIterator[str]], status: int = 200) -> None:
        self.chunks = chunks
        self.status = status
        self.requests: list[httpx2.Request] = []
        self.closed = False

    def transport(self) -> httpx2.MockTransport:
        async def handler(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            if self.status != 200:
                return httpx2.Response(self.status)
            return httpx2.Response(
                200, content=self._body(), headers={"content-type": "text/event-stream"}
            )

        return httpx2.MockTransport(handler)

    async def _body(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.chunks():
                yield chunk.encode()
        finally:
            self.closed = True


def scripted(*chunks: str) -> Callable[[], AsyncIterator[str]]:
    async def gen() -> AsyncIterator[str]:
        for chunk in chunks:
            yield chunk

    return gen


def client_for(agent: Agent, **settings: Any) -> TestClient:
    app = create_app(
        executor=lambda *_: ([], []),
        warm=False,
        agent_transport=agent.transport(),
        chat_settings=ChatSettings(**settings) if settings else None,
    )
    return TestClient(app)


def events(body: str) -> list[tuple[str, dict[str, str]]]:
    out = []
    for block in body.split("\n\n"):
        if block.startswith("event:"):
            name, payload = block.split("\n", 1)
            out.append((name[6:].strip(), json.loads(payload[5:])))
    return out


def ask(client: TestClient, message: str = "receita de outubro?", **extra: Any) -> Any:
    return client.post("/api/chat", json={"message": message, **extra}, headers=HEADERS)


def test_streams_deltas_then_done_with_the_full_text_and_fonte() -> None:
    agent = Agent(
        scripted(
            delta("A receita de outubro "),
            delta("foi de R$ 4.122.460,00.\n"),
            delta(FONTE),
            message_done(ANSWER),
            "data: [DONE]\n\n",
        )
    )
    response = ask(client_for(agent), conversation_id="conv-1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    got = events(response.text)
    assert [name for name, _ in got] == ["delta", "delta", "delta", "done"]
    assert "".join(p["text"] for n, p in got if n == "delta") == ANSWER
    assert got[-1][1]["text"] == ANSWER  # o backend não mexe no texto (nem no número)
    assert "Fonte:" in got[-1][1]["text"]
    assert agent.closed


def test_forwards_the_user_token_and_the_conversation_id() -> None:
    agent = Agent(scripted(message_done("ok")))
    ask(client_for(agent), message="  olá  ", conversation_id="conv-1")
    (request,) = agent.requests
    assert str(request.url) == "https://agent.example/invocations"
    assert request.headers["authorization"] == "Bearer user-token"
    body = json.loads(request.content)
    assert body == {
        "input": [{"role": "user", "content": "olá"}],
        "stream": True,
        "context": {"conversation_id": "conv-1"},
    }


def test_without_conversation_id_there_is_no_context() -> None:
    agent = Agent(scripted(message_done("ok")))
    ask(client_for(agent))
    assert "context" not in json.loads(agent.requests[0].content)


@pytest.mark.parametrize("message", ["", "   ", "\n"])
def test_empty_message_is_400(message: str) -> None:
    agent = Agent(scripted())
    response = ask(client_for(agent), message=message)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_ARGUMENT"
    assert not agent.requests


def test_message_size_limit() -> None:
    agent = Agent(scripted(message_done("ok")))
    client = client_for(agent)
    assert ask(client, message="a" * MAX_MESSAGE_CHARS).status_code == 200
    too_big = ask(client, message="a" * (MAX_MESSAGE_CHARS + 1))
    assert too_big.status_code == 400
    assert too_big.json()["detail"]["code"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "payload", [None, [], "texto", {"message": 3}, {"message": "ok", "conversation_id": 1}]
)
def test_invalid_body_is_400(payload: Any) -> None:
    client = client_for(Agent(scripted()))
    response = client.post("/api/chat", json=payload, headers=HEADERS)
    assert response.status_code == 400


def test_invalid_json_is_400() -> None:
    client = client_for(Agent(scripted()))
    response = client.post("/api/chat", content=b"{nao", headers=HEADERS)
    assert response.status_code == 400


def test_without_user_token_is_403_and_never_calls_the_agent() -> None:
    agent = Agent(scripted(message_done("ok")))
    response = client_for(agent).post("/api/chat", json={"message": "oi"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
    assert not agent.requests


@pytest.mark.parametrize("status", [401, 403, 302])
def test_agent_denies_the_user_is_403(status: int) -> None:
    response = ask(client_for(Agent(scripted(), status=status)))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


@pytest.mark.parametrize("status", [500, 502, 503, 404])
def test_agent_down_is_503(status: int) -> None:
    response = ask(client_for(Agent(scripted(), status=status)))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENT_UNAVAILABLE"


def test_agent_unreachable_is_503() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("recusou", request=request)

    app = create_app(
        executor=lambda *_: ([], []), warm=False, agent_transport=httpx2.MockTransport(refuse)
    )
    response = ask(TestClient(app))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENT_UNAVAILABLE"


def test_not_configured_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_AGENT_URL")
    response = ask(client_for(Agent(scripted())))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENT_UNAVAILABLE"


def test_agent_429_is_a_rate_limited_event() -> None:
    response = ask(client_for(Agent(scripted(), status=429)))
    assert response.status_code == 200
    assert events(response.text) == [
        ("error", {"code": "RATE_LIMITED", "message": "limite de uso do agente atingido"})
    ]


def test_agent_error_event_is_agent_error() -> None:
    agent = Agent(scripted(delta("A recei"), data({"type": "error", "message": "boom"})))
    got = events(ask(client_for(agent)).text)
    assert [n for n, _ in got] == ["delta", "error"]
    assert got[-1][1]["code"] == "AGENT_ERROR"
    assert agent.closed


def test_agent_gateway_429_inside_the_stream_is_rate_limited() -> None:
    agent = Agent(scripted(data({"type": "error", "message": "REQUEST_LIMIT_EXCEEDED"})))
    assert events(ask(client_for(agent)).text)[-1][1]["code"] == "RATE_LIMITED"


def test_stream_cut_in_the_middle_is_an_error_and_invents_nothing() -> None:
    agent = Agent(scripted(delta("A receita "), delta("foi de")))  # EOF sem o item final
    got = events(ask(client_for(agent)).text)
    assert [n for n, _ in got] == ["delta", "delta", "error"]
    assert got[-1][1]["code"] == "AGENT_ERROR"
    assert all(n != "done" for n, _ in got)


def test_stream_that_dies_with_a_network_error_is_agent_unavailable() -> None:
    async def broken() -> AsyncIterator[str]:
        yield delta("A receita ")
        raise httpx2.ReadError("conexão caiu")

    got = events(ask(client_for(Agent(broken))).text)
    assert got[-1][0] == "error"
    assert got[-1][1]["code"] == "AGENT_UNAVAILABLE"


def test_garbage_from_the_agent_is_agent_error() -> None:
    got = events(ask(client_for(Agent(scripted("data: {nao json\n\n")))).text)
    assert got == [("error", {"code": "AGENT_ERROR", "message": "resposta do agente ilegível"})]


def test_idle_timeout() -> None:
    async def silent() -> AsyncIterator[str]:
        yield delta("A receita ")
        await asyncio.sleep(5)
        yield message_done("tarde demais")

    agent = Agent(silent)
    got = events(
        ask(client_for(agent, idle_timeout_s=0.2, ping_interval_s=0.05, total_timeout_s=10)).text
    )
    assert [n for n, _ in got] == ["delta", "error"]
    assert got[-1][1]["code"] == "TIMEOUT"
    assert agent.closed  # fechou a conexão com o agente


def test_total_timeout_even_when_the_agent_keeps_talking() -> None:
    async def chatty() -> AsyncIterator[str]:
        for _ in range(1000):
            yield delta("x")
            await asyncio.sleep(0.02)

    agent = Agent(chatty)
    got = events(
        ask(client_for(agent, total_timeout_s=0.3, idle_timeout_s=10, ping_interval_s=10)).text
    )
    assert got[-1][0] == "error"
    assert got[-1][1]["code"] == "TIMEOUT"
    assert agent.closed


def test_ping_is_a_comment_not_an_event() -> None:
    async def slow() -> AsyncIterator[str]:
        await asyncio.sleep(0.25)
        yield message_done(ANSWER)

    body = ask(client_for(Agent(slow), ping_interval_s=0.05, idle_timeout_s=10)).text
    assert ": ping" in body
    assert [n for n, _ in events(body)] == ["done"]


def test_rate_limit_per_user() -> None:
    agent = Agent(scripted(message_done("ok")))
    client = client_for(agent, rate_limit=2)
    assert ask(client).status_code == 200
    assert ask(client).status_code == 200
    third = ask(client)
    assert third.status_code == 429
    assert third.json()["detail"]["code"] == "RATE_LIMITED"
    assert "retry-after" in third.headers
    assert len(agent.requests) == 2
    other = client.post(
        "/api/chat",
        json={"message": "oi"},
        headers={**HEADERS, "x-forwarded-email": "bia@exemplo.com"},
    )
    assert other.status_code == 200  # o limite é por usuário


def test_rate_limiter_window_slides() -> None:
    now = [0.0]
    limiter = RateLimiter(2, 60, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    now[0] = 61
    assert limiter.allow("a")


def test_chat_never_touches_the_warehouse() -> None:
    calls: list[str] = []

    def executor(sql: str, params: Any) -> tuple[list[str], list[list[Any]]]:
        calls.append(sql)
        return [], []

    app = create_app(
        executor=executor,
        warm=False,
        agent_transport=Agent(scripted(message_done("ok"))).transport(),
    )
    assert ask(TestClient(app)).status_code == 200
    assert calls == []


def test_done_uses_the_last_non_empty_message() -> None:
    agent = Agent(
        scripted(
            delta("Consultando"),
            message_done("Consultando"),
            message_done(ANSWER),
            message_done(""),
        )
    )
    got = events(ask(client_for(agent)).text)
    assert got[-1] == ("done", {"text": ANSWER})
