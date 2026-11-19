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
        "celular: 11912345678",
        "whatsapp 11 91234 5678",
        "o documento 12345678909",
        "Fale com joao.silva@exemplo.com.br",
    ],
)
def test_pii_is_masked(text: str) -> None:
    masked, changed = mask_pii(text)
    assert changed
    assert MASK in masked
    for secret in ("123.456.789-09", "12345678909", "91234-5678", "joao.silva@", "912345678"):
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
        "entre 2025-2026 e faixa 1000-2000 recargas, ticket 9999-1234",
        "Em 2025-2026 a receita foi de R$ 48.880.720,00.",
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


def test_guard_event_with_a_real_responses_event() -> None:
    from agent_server.guardrails import guard_event

    responses = pytest.importorskip("mlflow.types.responses")  # só no ambiente do App
    ResponsesAgentStreamEvent = responses.ResponsesAgentStreamEvent
    create_text_output_item = responses.create_text_output_item

    event = ResponsesAgentStreamEvent(
        type="response.output_item.done",
        item=create_text_output_item("fale com a@b.com", id="m1"),
    )
    assert guard_event(event) == (True, True)
    assert MASK in event.item["content"][0]["text"]


# --- StreamMasker (ADR-0023) ---

import random  # noqa: E402

from agent_server.guardrails import HOLD_BACK, StreamMasker  # noqa: E402

_SECRETS = {
    "cpf": "123.456.789-09",
    "cpf_label": "CPF: 12345678909",
    "phone": "(11) 91234-5678",
    "phone_intl": "+55 11 91234-5678",
    "phone_label": "celular: 11 91234 5678",
    "email": "joao.silva@exemplo.com.br",
}


def _stream(text: str, step: int) -> tuple[str, StreamMasker, list[str]]:
    masker = StreamMasker()
    parts = [masker.feed(text[i : i + step]) for i in range(0, len(text), step)]
    parts.append(masker.finish())
    return "".join(parts), masker, parts


@pytest.mark.parametrize("name", sorted(_SECRETS))
@pytest.mark.parametrize("step", [1, 3, 7, 25])
def test_stream_pii_cut_at_any_position_is_masked(name: str, step: int) -> None:
    secret = _SECRETS[name]
    for pad in range(0, 60):  # o segredo começa em qualquer posição de um texto de ~60+ caracteres
        text = ("x" * pad) + " " + secret + " " + ("y" * (60 - pad))
        out, masker, parts = _stream(text, step)
        assert out == mask_pii(text)[0]
        # nenhum pedaço parcial do segredo saiu antes do fim
        joined = ""
        for part in parts:
            joined += part
            for frag in ("123.456", "91234", "joao.silva", "12345678"):
                assert frag not in joined
        assert masker.masked_any


def test_stream_pii_secret_with_long_tail_without_spaces() -> None:
    text = "Ligue (11) 91234-5678" + "z" * 80
    out, _, _ = _stream(text, 5)
    assert out == mask_pii(text)[0]
    assert "91234" not in out


def test_stream_equals_full_mask_on_clean_text_and_holds_back() -> None:
    text = "A receita de R$ 4.122.460,00 no mês foi alta. " * 5 + "Fonte: semantic.mv_recharges"
    masker = StreamMasker()
    emitted = ""
    for i in range(0, len(text), 4):
        emitted += masker.feed(text[i : i + 4])
        assert len(masker.raw) - len(emitted) >= 0
    assert emitted != text  # ainda retém o final
    assert len(text) - len(emitted) >= HOLD_BACK
    emitted += masker.finish()
    assert emitted == text
    assert not masker.masked_any


def test_stream_random_fuzz_matches_full_mask() -> None:
    rng = random.Random(7)  # noqa: S311 (fuzz determinístico, não é criptografia)
    words = ["receita", "R$ 1.234,56", *sorted(_SECRETS.values()), "PA", "2026-10", "tel", "fim."]
    for _ in range(200):
        text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 30)))
        out, _, _ = _stream(text, rng.randint(1, 9))
        assert out == mask_pii(text)[0]


# --- StreamGuard: fiação no stream de eventos ---

from types import SimpleNamespace  # noqa: E402

from agent_server.guardrails import StreamGuard  # noqa: E402


def _delta(text: str, item_id: str = "m1") -> SimpleNamespace:
    return SimpleNamespace(
        type="response.output_text.delta", delta=text, item_id=item_id, item=None
    )


def _done(text: str) -> SimpleNamespace:
    item = {"type": "message", "content": [{"type": "output_text", "text": text}]}
    return SimpleNamespace(type="response.output_item.done", item=item)


def _run(events: list[SimpleNamespace]) -> tuple[list[object], StreamGuard]:
    guard = StreamGuard(
        lambda text, item_id: SimpleNamespace(type="delta", delta=text, item_id=item_id)
    )
    out: list[object] = []
    for event in events:
        out.extend(guard.process(event))
    return out, guard


def test_guard_deltas_equal_the_final_item_and_the_trace_flag_is_set() -> None:
    raw = "Dono: 123.456.789-09, ligue (11) 91234-5678. " + "Receita R$ 4.122.460,00. " * 4
    out, guard = _run([_delta(raw[i : i + 6]) for i in range(0, len(raw), 6)] + [_done(raw)])
    deltas = "".join(e.delta for e in out if getattr(e, "type", "") == "delta")  # type: ignore[attr-defined]
    final = out[-1].item["content"][0]["text"]  # type: ignore[attr-defined]
    assert out[-1].type == "response.output_item.done"  # type: ignore[attr-defined]
    assert deltas == final == mask_pii(raw)[0]  # nada vaza e o que sai bate com o item final
    assert "123.456" not in deltas and "91234" not in deltas
    assert guard.pii_masked


def test_guard_flushes_held_text_before_each_done_and_resets_between_items() -> None:
    out, guard = _run(
        [_delta("Olá, tudo bem"), _done("Olá, tudo bem"), _delta("Segunda"), _done("Segunda")]
    )
    kinds = [e.type for e in out]  # type: ignore[attr-defined]
    assert kinds == ["delta", "response.output_item.done", "delta", "response.output_item.done"]
    assert out[0].delta == "Olá, tudo bem" and out[2].delta == "Segunda"  # type: ignore[attr-defined]
    assert not guard.pii_masked


def test_guard_passes_other_events_through() -> None:
    tool = SimpleNamespace(type="response.output_item.done", item={"type": "function_call"})
    out, _ = _run([tool])
    assert out == [tool]
