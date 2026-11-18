"""Erros padronizados do MCP (SPEC-006 §4): um código estável e uma mensagem, nunca stack trace.

O cliente vê `CODIGO: mensagem`. O `RATE_LIMITED` fica para a P11.4 (limitador por usuário).
"""

from __future__ import annotations


class McpError(Exception):
    """Erro do contrato do §4. `code` é o que o cliente recebe, prefixando a mensagem."""

    code = "INTERNAL"

    def render(self) -> str:
        return f"{self.code}: {self}"


class InvalidArgument(McpError, ValueError):
    """Medida, dimensão ou filtro fora da lista fechada; `limit` acima do máximo; mês inválido."""

    code = "INVALID_ARGUMENT"


class PermissionDenied(McpError):
    """O usuário não tem `SELECT` na metric view."""

    code = "PERMISSION_DENIED"


class WarehouseUnavailable(McpError):
    """Warehouse parado ou em timeout, depois de 1 nova tentativa."""

    code = "WAREHOUSE_UNAVAILABLE"


class ResultTooLarge(McpError):
    """Mais de 500 linhas: o cliente deve agregar mais ou filtrar."""

    code = "RESULT_TOO_LARGE"


# Só códigos de erro do Databricks (não frases soltas): uma falha nossa não vira "sem permissão".
_PERMISSION_CODES = ("PERMISSION_DENIED", "INSUFFICIENT_PERMISSIONS")
_UNAVAILABLE_CODES = ("TEMPORARILY_UNAVAILABLE", "SERVICE_UNAVAILABLE")
# Tipos do conector SQL e do transporte HTTP (urllib3/requests), por nome para não importá-los aqui.
_TRANSPORT_TYPES = frozenset(
    {"RequestError", "MaxRetryError", "ConnectTimeout", "ReadTimeout", "ConnectionError"}
)


def classify(exc: BaseException) -> McpError | None:
    """Mapeia uma falha do conector SQL para o contrato do §4; `None` se não for conhecida.

    A mensagem devolvida é fixa: o texto original do conector pode trazer host, caminho do
    warehouse ou trecho de SQL, e não vai para o cliente (só o tipo vai para o log do App).
    """
    if isinstance(exc, McpError):
        return exc
    text = str(exc).upper()
    if any(code in text for code in _PERMISSION_CODES):
        return PermissionDenied("sem permissão de SELECT na metric view consultada")
    if (
        isinstance(exc, TimeoutError | ConnectionError)
        or type(exc).__name__ in _TRANSPORT_TYPES
        or any(code in text for code in _UNAVAILABLE_CODES)
    ):
        return WarehouseUnavailable("o SQL warehouse está parado ou não respondeu; tente de novo")
    return None


def too_large(limit: int) -> ResultTooLarge:
    return ResultTooLarge(f"mais de {limit} linhas: agregue mais (level) ou filtre (uf)")
