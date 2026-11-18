"""Servidor FastMCP do Atlas (SPEC-006 §2): Streamable HTTP em /mcp."""

from __future__ import annotations

import os

from fastmcp import FastMCP

from atlas_mcp.health import health as build_health

mcp = FastMCP("atlas-mcp")


@mcp.tool(annotations={"readOnlyHint": True})
def health() -> dict[str, str]:
    """Estado do servidor, do SQL warehouse e a versão do App."""
    return build_health()


def main() -> None:
    port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port, path="/mcp")  # noqa: S104 - o App escuta atrás do proxy


if __name__ == "__main__":
    main()
