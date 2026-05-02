"""FastMCP server setup for docs-mcp (multi-source documentation)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

from cern_mkdocs_mcp.config import (
    DocSource,
    get_default_sources,
    load_sources,
)
from cern_mkdocs_mcp.nomenclature import ATLAS_SOFTWARE_DOCS_GUIDE
from cern_mkdocs_mcp.resources import register as register_resources
from cern_mkdocs_mcp.tools import fetch, search
from cern_mkdocs_mcp.tools._index import DocsIndex

DEFAULT_GITLAB_API = "https://gitlab.cern.ch/api/v4"


def _build_instructions(sources: dict[str, DocSource]) -> str:
    """Build the FastMCP `instructions` string from the loaded sources.

    The instructions enumerate the available source IDs so the agent can
    pick one without an extra resource read.
    """
    rows = "\n".join(
        f"  - {src.id} - {src.name} ({src.docs_site_url})"
        for src in sorted(sources.values(), key=lambda s: s.id)
    )
    return (
        "MCP server for searching multiple MkDocs-based documentation "
        "sites via a unified interface. Provides keyword search (BM25 "
        "over published MkDocs search payloads) and Markdown source "
        "retrieval. Read-only, no auth.\n\n"
        f"Registered sources:\n{rows}\n\n"
        "Use search_docs(source='<id>') to query one source. "
        "Each source is independent; cross-source queries require one "
        "call per source.\n\n"
        + ATLAS_SOFTWARE_DOCS_GUIDE
    )


def _make_mcp(
    host: str = "127.0.0.1",
    port: int = 8000,
    config_path: Path | None = None,
) -> FastMCP:
    """Build and return a configured FastMCP instance.

    Args:
        host: Bind address (passed to FastMCP for HTTP transport).
        port: Port (passed to FastMCP for HTTP transport).
        config_path: Optional path to a custom ``docs_sources.json``.
            When omitted, the package-bundled file is used.
    """
    sources = (
        load_sources(config_path) if config_path is not None
        else get_default_sources()
    )

    @asynccontextmanager
    async def _lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
        """Open a shared httpx client and one lazy BM25 index per source.

        Indices are not populated here - the first ``search_docs`` call
        per source triggers ``DocsIndex.ensure_fresh`` which downloads
        ``/search/search_index.json`` and builds the BM25 ranker. This
        keeps server start-up fast even if individual docs sites are
        briefly unreachable.
        """
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient(timeout=30.0) as http:
            indices: dict[str, DocsIndex] = {
                source_id: DocsIndex(search_index_url=src.search_index_url)
                for source_id, src in sources.items()
            }

            yield {
                "http": http,
                "indices": indices,
                "sources": sources,
                "gitlab_api": DEFAULT_GITLAB_API,
            }

    mcp = FastMCP(
        "docs-mcp",
        lifespan=_lifespan,
        instructions=_build_instructions(sources),
        host=host,
        port=port,
    )

    for _module in [search, fetch]:
        _module.register(mcp)

    register_resources(mcp, sources)

    return mcp


def serve(
    transport: str = "stdio",
    host: str = "0.0.0.0",  # noqa: S104 - container binds public by design
    port: int = 8000,
    config_path: Path | None = None,
) -> None:
    """Start the MCP server.

    Args:
        transport: ``"stdio"`` for CLI usage, ``"streamable-http"`` for
            remote / OpenWebUI / opencode-remote-MCP clients.
        host: Bind address for HTTP transport (default ``0.0.0.0``).
        port: Port for HTTP transport (default 8000).
        config_path: Optional path to a custom ``docs_sources.json``.
    """
    mcp = _make_mcp(host=host, port=port, config_path=config_path)
    mcp.run(transport=transport)
