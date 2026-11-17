"""Configuração do agente por variáveis ATLAS_* (SPEC-005 §2, ADR-0007).

Sem imports pesados: o módulo é testado no CI sem mlflow nem langchain.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_LLM_SERVICE = "system.ai.gpt-oss-120b"
DEFAULT_EXPERIMENT = "/Shared/atlas/agent"
SUPPORTED_GATEWAY_MODES = ("unity",)  # "classic" (plano B do ADR-0007) não foi acionado

# Lista fechada da SPEC-005 §3 (as mesmas de `eval.scorers.ALLOWED_TOOLS`, menos `ask_genie`).
UC_FUNCTIONS = ("fn_list_metrics", "fn_metric_by_region", "fn_compare_months")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
_SPACE_ID = re.compile(r"^[0-9a-f]{32}$")
_WAREHOUSE_ID = re.compile(r"^[0-9a-f]{8,32}$")

# catalog.schema.service: o nome curto cai no endpoint legado e dá 403 (S0.1).
_THREE_PART_NAME = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_.-]+$")


class ConfigError(ValueError):
    """Variável ATLAS_* inválida."""


@dataclass(frozen=True)
class AgentConfig:
    gateway_mode: str
    llm_service: str
    app_version: str
    prompt_version: str
    send_request_tags: bool
    catalog: str
    genie_space_id: str | None
    warehouse_id: str | None

    def trace_tags(self, user: str | None) -> dict[str, str]:
        """Tags de cada trace (SPEC-005 §5)."""
        return {
            "user": user or "unknown",
            "app_version": self.app_version,
            "prompt_version": self.prompt_version,
            "llm_service": self.llm_service,
        }

    def uc_function_names(self) -> list[str]:
        """As UC functions da lista fechada da SPEC-005 §3, qualificadas no catálogo do target."""
        return [f"{self.catalog}.semantic.{name}" for name in UC_FUNCTIONS]

    def request_tags(self) -> dict[str, str]:
        """Tags enviadas ao gateway para dimensionar o uso por agente (não validado no S0.2)."""
        return {"app": "agent-atlas", "prompt_version": self.prompt_version}


def load_config(env: Mapping[str, str] | None = None) -> AgentConfig:
    e = os.environ if env is None else env
    mode = e.get("ATLAS_GATEWAY_MODE", "unity").strip().lower()
    if mode not in SUPPORTED_GATEWAY_MODES:
        raise ConfigError(
            f"ATLAS_GATEWAY_MODE={mode!r} não suportado; use um de {SUPPORTED_GATEWAY_MODES}. "
            "O plano B 'classic' (ADR-0007) não foi implementado."
        )
    service = e.get("ATLAS_LLM_SERVICE", DEFAULT_LLM_SERVICE).strip()
    if not _THREE_PART_NAME.match(service):
        raise ConfigError(
            f"ATLAS_LLM_SERVICE={service!r} deve ter três partes (catalog.schema.service); "
            "o nome curto cai no endpoint legado e dá 403."
        )
    catalog = e.get("ATLAS_CATALOG", "atlas").strip()
    if not _IDENTIFIER.match(catalog):
        raise ConfigError(f"ATLAS_CATALOG={catalog!r} deve ser um identificador simples.")
    space_id = e.get("ATLAS_GENIE_SPACE_ID", "").strip() or None
    if space_id is not None and not _SPACE_ID.match(space_id):
        raise ConfigError("ATLAS_GENIE_SPACE_ID deve ter 32 caracteres hexadecimais.")
    warehouse_id = e.get("DATABRICKS_WAREHOUSE_ID", "").strip() or None
    if warehouse_id is not None and not _WAREHOUSE_ID.match(warehouse_id):
        raise ConfigError("DATABRICKS_WAREHOUSE_ID deve ser um id hexadecimal de warehouse.")
    return AgentConfig(
        gateway_mode=mode,
        llm_service=service,
        app_version=e.get("ATLAS_APP_VERSION", "dev").strip() or "dev",
        prompt_version=e.get("ATLAS_PROMPT_VERSION", "p10.3-tools").strip() or "p10.3-tools",
        send_request_tags=e.get("ATLAS_LLM_REQUEST_TAGS", "0").strip() in ("1", "true"),
        catalog=catalog,
        genie_space_id=space_id,
        warehouse_id=warehouse_id,
    )
