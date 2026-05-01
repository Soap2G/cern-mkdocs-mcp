"""``search_atlas_software_docs`` - keyword search over the docs index.

Wraps :class:`atlas_software_docs_mcp.tools._index.DocsIndex` (BM25 over
the published MkDocs search payload). Returns a token-efficient summary
(arcade.dev Response Shaper / Token-Efficient Response): titles, URLs,
snippets only - no body. The agent retrieves bodies via
``fetch_atlas_software_doc``.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from atlas_software_docs_mcp.tools._helpers import format_error

_MAX_LIMIT = 25
_KNOWN_SECTIONS = (
    "athena",
    "developers",
    "trigger",
    "analysis",
    "shifts-and-infrastructure",
)


def register(mcp: FastMCP) -> None:
    """Register the search tool."""

    @mcp.tool()
    async def search_atlas_software_docs(
        query: str,
        section: str | None = None,
        limit: int = 10,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Keyword search across the ATLAS offline software documentation.

        Returns ``{title, url, path, section, score, snippet}`` per hit.
        NOT for ATLAS Open Data - use the ``cernopendata`` or
        ``atlasopenmagic`` MCPs for that.

        After a hit, call ``fetch_atlas_software_doc(url)`` to retrieve
        the Markdown body (full, outline, or one named section).

        Args:
            query: Free-text query. Word-token matched (case-insensitive)
                and ranked by BM25. Multi-token queries are AND-biased
                via BM25 scoring, not strict AND.
            section: Restrict to one top-level section. One of:
                ``athena``, ``developers``, ``trigger``, ``analysis``,
                ``shifts-and-infrastructure``. Omit to search the whole
                site.
            limit: Max hits returned (1-25, default 10). Smaller is more
                token-efficient.
        """
        limit = max(1, min(int(limit), _MAX_LIMIT))
        section_norm = section.strip().lower() if section else None
        if section_norm and section_norm not in _KNOWN_SECTIONS:
            return format_error(
                ValueError(f"Unknown section: {section_norm!r}"),
                recovery=[
                    f"Pass one of: {', '.join(_KNOWN_SECTIONS)}.",
                    "Or omit `section` to search the whole site.",
                ],
            )

        ctxd = ctx.request_context.lifespan_context
        http = ctxd["http"]
        index = ctxd["index"]
        try:
            await index.ensure_fresh(http)
        except Exception as exc:  # noqa: BLE001
            return format_error(exc, recovery=[
                "The MkDocs search index could not be loaded. Try again "
                "shortly.",
                "Verify the docs site is up: "
                "https://atlas-software.docs.cern.ch/",
            ])

        results = index.search(query, limit=limit, section=section_norm)
        return json.dumps(
            {
                "query": query,
                "section": section_norm,
                "limit": limit,
                "returned": len(results),
                "results": results,
                "hint": (
                    "No matches - try broader / fewer terms, or drop the "
                    "`section` filter."
                    if not results
                    else None
                ),
                "next_action": (
                    "Call fetch_atlas_software_doc(url_or_path) on a "
                    "result to retrieve the Markdown body."
                    if results
                    else None
                ),
            },
            default=str,
        )
