"""FastMCP server setup for atlas-software-docs-mcp."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from atlas_software_docs_mcp.nomenclature import ATLAS_SOFTWARE_DOCS_GUIDE
from atlas_software_docs_mcp.resources import register as register_resources
from atlas_software_docs_mcp.tools import fetch, search
from atlas_software_docs_mcp.tools._index import DocsIndex

DEFAULT_DOCS_BASE = "https://atlas-software.docs.cern.ch"
DEFAULT_GITLAB_API = "https://gitlab.cern.ch/api/v4"
# atlas/software-docs/atlas-software-docs (public, no token needed)
DEFAULT_GITLAB_PROJECT_ID = "202647"

_INSTRUCTIONS = (
    "MCP server for ATLAS offline software documentation "
    "(https://atlas-software.docs.cern.ch). Provides keyword search "
    "(BM25 over the published MkDocs search payload) and Markdown "
    "source retrieval for Athena, the developer guide, the trigger "
    "primer, and the analysis software tutorial. Read-only, no auth.\n\n"
    "Scope: ATLAS *internal/offline* software. NOT ATLAS Open Data - "
    "for open datasets and example notebooks use the cernopendata or "
    "atlasopenmagic MCPs.\n\n"
    + ATLAS_SOFTWARE_DOCS_GUIDE
)


def _make_mcp(
    host: str = "127.0.0.1",
    port: int = 8000,
    docs_base: str = DEFAULT_DOCS_BASE,
    gitlab_api: str = DEFAULT_GITLAB_API,
    project_id: str = DEFAULT_GITLAB_PROJECT_ID,
) -> FastMCP:
    """Build and return a configured FastMCP instance.

    Args:
        host: Bind address (passed to FastMCP for HTTP transport).
        port: Port (passed to FastMCP for HTTP transport).
        docs_base: Base URL of the rendered MkDocs site. Override to point
            at a staging build.
        gitlab_api: GitLab REST API base URL (e.g.
            ``https://gitlab.cern.ch/api/v4``). Used by
            ``fetch_atlas_software_doc`` to retrieve raw Markdown.
        project_id: Numeric GitLab project ID (or URL-encoded path) of the
            docs source repo.
    """

    @asynccontextmanager
    async def _lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
        """Open a shared httpx client and a lazily-loaded BM25 index.

        The index is **not** populated here - the first ``search`` call
        triggers ``DocsIndex.ensure_fresh`` which downloads
        ``/search/search_index.json`` and builds the BM25 ranker. This
        keeps server start-up fast even if the docs site is briefly
        unreachable.
        """
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient(timeout=30.0) as http:
            index = DocsIndex(docs_base=docs_base)
            yield {
                "http": http,
                "index": index,
                "docs_base": docs_base,
                "gitlab_api": gitlab_api,
                "project_id": project_id,
            }

    mcp = FastMCP(
        "atlas-software-docs-mcp",
        lifespan=_lifespan,
        instructions=_INSTRUCTIONS,
        host=host,
        port=port,
    )

    for _module in [search, fetch]:
        _module.register(mcp)

    register_resources(mcp)

    return mcp


def serve(
    transport: str = "stdio",
    host: str = "0.0.0.0",  # noqa: S104 - container binds public by design
    port: int = 8000,
    docs_base: str = DEFAULT_DOCS_BASE,
    gitlab_api: str = DEFAULT_GITLAB_API,
    project_id: str = DEFAULT_GITLAB_PROJECT_ID,
) -> None:
    """Start the MCP server.

    Args:
        transport: ``"stdio"`` for CLI usage, ``"streamable-http"`` for
            remote / OpenWebUI / opencode-remote-MCP clients.
        host: Bind address for HTTP transport (default ``0.0.0.0``).
        port: Port for HTTP transport (default 8000).
        docs_base: Override the rendered docs site URL.
        gitlab_api: Override the GitLab API base URL.
        project_id: Override the GitLab project ID for the docs repo.
    """
    mcp = _make_mcp(
        host=host,
        port=port,
        docs_base=docs_base,
        gitlab_api=gitlab_api,
        project_id=project_id,
    )
    mcp.run(transport=transport)
