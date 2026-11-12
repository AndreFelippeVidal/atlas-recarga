"""Códigos de saída do atlas-cli (SPEC-001 §2)."""

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    INVALID_FLAG = 2
    REFERENCE_DATA_INVALID = 3  # referência IBGE ausente ou inválida
    UPLOAD_FAILED = 4
