import pytest
from agent_server.guardrails import MASK, is_rate_limited, mask_pii


@pytest.mark.parametrize(
    "text",
    [
        "O CPF 123.456.789-09 é do dono.",
        "CPF: 12345678909",
        "Ligue para (11) 91234-5678.",
        "Ligue +55 11 91234-5678 agora",
        "Telefone 91234-5678",
        "Fale com joao.silva@exemplo.com.br",
    ],
)
def test_pii_is_masked(text: str) -> None:
    masked, changed = mask_pii(text)
    assert changed
    assert MASK in masked
    for secret in ("123.456.789-09", "12345678909", "91234-5678", "joao.silva@"):
        assert secret not in masked


@pytest.mark.parametrize(
    "text",
    [
        "Receita de R$ 4.122.460,00 em 2026-10-01.",
        "Município 1501402 (Belém), DDD 91.",
        "Lote COM-2026-10-v1 com 4.798 linhas.",
        "Fonte: semantic.mv_recharges · gross_revenue · uf = 'PA', recharge_month = 2026-10",
        "Taxa de estorno de 1,25% e ticket médio de R$ 21,40.",
        "Total de 12345678901 recargas",
    ],
)
def test_business_numbers_are_kept(text: str) -> None:
    assert mask_pii(text) == (text, False)


def test_label_keeps_label() -> None:
    assert mask_pii("CPF: 12345678909")[0] == f"CPF: {MASK}"


class _Err(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(Exception):
    pass


def test_rate_limit_by_status_code() -> None:
    assert is_rate_limited(_Err("x", status_code=429))
    assert not is_rate_limited(_Err("x", status_code=500))


def test_rate_limit_by_name_and_text() -> None:
    assert is_rate_limited(RateLimitError("slow down"))
    assert is_rate_limited(Exception("REQUEST_LIMIT_EXCEEDED: rate limit"))
    assert is_rate_limited(Exception("Error code: 429 - too many"))
    assert not is_rate_limited(Exception("ENDPOINT_NOT_FOUND"))


def test_rate_limit_through_the_cause_chain() -> None:
    try:
        try:
            raise _Err("upstream", status_code=429)
        except _Err as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert is_rate_limited(outer)


def test_guard_event_drops_deltas_and_masks_final_message() -> None:
    from types import SimpleNamespace

    from agent_server.guardrails import guard_event

    delta = SimpleNamespace(type="response.output_text.delta", item=None)
    assert guard_event(delta) == (False, False)

    part = {"type": "output_text", "text": "fale com a@b.com", "annotations": []}
    done = SimpleNamespace(
        type="response.output_item.done",
        item={"type": "message", "role": "assistant", "content": [part]},
    )
    assert guard_event(done) == (True, True)
    assert part["text"] == f"fale com {MASK}"

    tool = SimpleNamespace(type="response.output_item.done", item={"type": "function_call"})
    assert guard_event(tool) == (True, False)
