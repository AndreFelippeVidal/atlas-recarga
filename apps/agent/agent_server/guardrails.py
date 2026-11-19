"""Guardrails determinísticos do agente (SPEC-005 §4 e §6, ADR-0021).

O gateway não tem guardrail de PII (a API do model service só tem roteamento, rate limit e
inference table), então a máscara vive aqui. Sem imports pesados: testado no CI sem mlflow.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

MASK = "[dado pessoal omitido]"
RATE_LIMIT_MESSAGE = "Limite de uso atingido, tente em 1 minuto."
RATE_LIMITED_ERROR_TYPE = "rate_limited"

# Só formatos com estrutura, para não mascarar valores em reais (R$ 4.122.460,00), códigos IBGE
# (7 dígitos), datas (2026-10-01) nem ids de lote (COM-2026-10-v1).
_CPF = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
# Número cru de 11 dígitos só com rótulo de documento por perto (contagens de negócio não têm).
_CPF_BY_LABEL = re.compile(r"(?i)\b(cpf|documento)\b(\W{0,3})\d{11}(?!\d)")
# Telefone: com DDD (parênteses ou +55) ou com rótulo (tel, fone, celular, whatsapp). Um `dddd-dddd`
# solto não conta: seria "2025-2026" ou "1000-2000".
_PHONE_DIGITS = r"(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}"
_PHONE = re.compile(
    r"(?<![\d.,-])(?:\+55[\s-]?\(?\d{2}\)?[\s-]?|\(\d{2}\)[\s-]?)9?\d{4}[\s-]?\d{4}(?!\d)"
)
_PHONE_BY_LABEL = re.compile(
    rf"(?i)\b(tel(?:efone)?|fone|celular|whats(?:app)?)\b(\W{{0,4}})(?:{_PHONE_DIGITS}|9?\d{{4}}[\s-]?\d{{4}})(?!\d)"
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask_pii(text: str) -> tuple[str, bool]:
    """Troca CPF, telefone e e-mail por `MASK`. Devolve o texto e se algo foi trocado."""
    masked = _CPF_BY_LABEL.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", text)
    masked = _PHONE_BY_LABEL.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", masked)
    for pattern in (_CPF, _EMAIL, _PHONE):
        masked = pattern.sub(MASK, masked)
    return masked, masked != text


HOLD_BACK = 40  # mais que qualquer padrão com espaço (telefone com DDD, rótulo de CPF)


class StreamMasker:
    """Mascara um texto que chega em deltas (ADR-0023, SPEC-005 §4).

    Acumula o texto bruto e só libera até uma fronteira de espaço que deixe pelo menos `HOLD_BACK`
    caracteres retidos no fim. Um corte só vale se nenhum padrão de PII o atravessa (o mascarado do
    prefixo é prefixo do mascarado do todo), então o que já saiu nunca fica incompleto.
    """

    def __init__(self) -> None:
        self.raw = ""
        self.emitted = ""
        self._cut = 0
        self.masked_any = False

    def _emit(self, masked: str) -> str:
        new = masked[len(self.emitted) :]
        self.emitted = masked
        return new

    def feed(self, delta: str) -> str:
        """Devolve o trecho mascarado novo que já pode sair (pode ser vazio)."""
        self.raw += delta
        limit = len(self.raw) - HOLD_BACK
        if limit <= self._cut:
            return ""
        full, _ = mask_pii(self.raw)
        for cut in range(limit, self._cut, -1):
            if not self.raw[cut - 1].isspace():
                continue
            prefix, hit = mask_pii(self.raw[:cut])
            if full.startswith(prefix):
                self._cut = cut
                self.masked_any = self.masked_any or hit
                return self._emit(prefix)
        return ""

    def finish(self) -> str:
        """Libera o resto, mascarado."""
        full, hit = mask_pii(self.raw)
        self.masked_any = self.masked_any or hit
        self._cut = len(self.raw)
        return self._emit(full)


class StreamGuard:
    """Fiação do `StreamMasker` no stream de eventos do agente (ADR-0023), sem imports pesados.

    `process(event)` devolve os eventos a emitir no lugar de `event`. `make_delta(text, item_id)`
    cria um evento de delta. Os deltas passam pelo mascarador; antes de cada
    `output_item.done` o que ficou retido é liberado, e o item traz o texto todo mascarado.
    """

    def __init__(self, make_delta: Callable[[str, str], Any]) -> None:
        self._make_delta = make_delta
        self._maskers: dict[str, StreamMasker] = {}
        self.pii_masked = False

    def process(self, event: Any) -> list[Any]:
        if event.type == "response.output_text.delta":
            masker = self._maskers.setdefault(event.item_id, StreamMasker())
            text = masker.feed(event.delta)
            return [self._make_delta(text, event.item_id)] if text else []
        keep, masked = guard_event(event)  # PII na saída (ADR-0021)
        out: list[Any] = []
        if keep and event.type == "response.output_item.done":
            for item_id, masker in self._maskers.items():
                if rest := masker.finish():
                    out.append(self._make_delta(rest, item_id))
            masked = masked or any(m.masked_any for m in self._maskers.values())
            self._maskers.clear()
        if masked:
            self.pii_masked = True
        if keep:
            out.append(event)
        return out


def is_rate_limited(error: BaseException) -> bool:
    """O gateway respondeu 429 (`RateLimitError`, `status_code` ou o texto do erro)."""
    for exc in (error, error.__cause__, error.__context__):
        if exc is None:
            continue
        if getattr(exc, "status_code", None) == 429:
            return True
        response = getattr(exc, "response", None)
        if getattr(response, "status_code", None) == 429:
            return True
        if type(exc).__name__ == "RateLimitError" or "REQUEST_LIMIT_EXCEEDED" in str(exc):
            return True
    return False


def guard_event(event: Any) -> tuple[bool, bool]:
    """Aplica a máscara de PII a um evento de saída do stream (duck-typed: `.type` e `.item`).

    Devolve `(manter, mascarou)`. Os deltas de texto passam por fora, pelo `StreamMasker`; aqui eles
    são descartados e o texto completo chega no `output_item.done` da mensagem, que é o que se
    mascara (fonte da verdade).
    """
    if event.type == "response.output_text.delta":
        return False, False
    item = getattr(event, "item", None)
    if event.type != "response.output_item.done" or not isinstance(item, dict):
        return True, False
    changed = False
    if item.get("type") == "message":
        for part in item.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part["text"], hit = mask_pii(part["text"])
                changed = changed or hit
    return True, changed
