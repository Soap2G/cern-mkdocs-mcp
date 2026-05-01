"""MCP resources exposing ATLAS software docs reference text to the LLM."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP  # noqa: TC002

from atlas_software_docs_mcp.nomenclature import ATLAS_SOFTWARE_DOCS_GUIDE


def register(mcp: FastMCP) -> None:
    """Register documentation resources with the MCP server."""

    @mcp.resource(
        "atlas-software-docs://guide",
        name="ATLAS Software Documentation Guide",
        description=(
            "Quick reference for the ATLAS offline software docs MCP: "
            "scope (Athena, developers, trigger, analysis tutorial, "
            "shifts/infra), the two tools (search + fetch), the "
            "supported fetch modes (markdown / outline / sections:<h>), "
            "and how this corpus differs from ATLAS Open Data."
        ),
        mime_type="text/plain",
    )
    def get_guide() -> str:
        return ATLAS_SOFTWARE_DOCS_GUIDE
