"""``fetch_atlas_software_doc`` - retrieve one page as Markdown.

Hits the GitLab Files Raw API for the docs source repo
(``atlas/software-docs/atlas-software-docs``). The repo is public, so no
token is needed.

Implements the arcade.dev Progressive Detail pattern via ``mode``:

- ``markdown`` - full body (default)
- ``outline`` - H1-H3 headings only
- ``sections:<heading>`` - just one section starting at a matching heading

Implements Natural Identifier: callers may pass a rendered URL, a
relative path, or a ``.md`` path - the tool resolves each shape to a
candidate ``docs/<path>`` and tries them in order.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlparse

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from atlas_software_docs_mcp.tools._helpers import format_error

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_OUTLINE_MAX_LEVEL = 3


def _candidate_source_paths(url_or_path: str) -> list[str]:
    """Map a docs URL or relative path to candidate ``docs/...`` paths.

    Handles three input shapes:
    - Rendered URL: ``https://atlas-software.docs.cern.ch/analysis/grid/``
    - Relative path: ``analysis/grid/`` or ``/analysis/grid/``
    - Direct .md path: ``analysis/grid.md`` (with or without ``docs/`` prefix)

    For directory-style inputs ``foo/bar/`` we return both ``foo/bar/index.md``
    (the MkDocs convention) and ``foo/bar.md`` (the alternative MkDocs
    convention). The tool tries them in order and falls through 404s.
    """
    raw = url_or_path.strip()
    if not raw:
        return []
    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme else raw
    path = path.split("#", 1)[0].split("?", 1)[0]
    path = path.strip("/")
    if path.startswith("docs/"):
        path = path[len("docs/"):]
    if not path:
        return ["docs/index.md"]
    if path.endswith(".md"):
        return [f"docs/{path}"]
    return [f"docs/{path}/index.md", f"docs/{path}.md"]


def _make_outline(markdown: str) -> list[dict[str, Any]]:
    """Extract H1-H3 headings as ``[{level, heading}, ...]``."""
    return [
        {"level": len(m.group(1)), "heading": m.group(2)}
        for m in _HEADING_RE.finditer(markdown)
        if len(m.group(1)) <= _OUTLINE_MAX_LEVEL
    ]


def _extract_section(markdown: str, heading: str) -> str:
    """Return the slice from a matching heading to the next equal-or-higher heading.

    Heading match is case-insensitive on the trimmed heading text. Returns
    ``""`` if no heading matches.
    """
    target = heading.strip().lower()
    matches = list(_HEADING_RE.finditer(markdown))
    for i, m in enumerate(matches):
        if m.group(2).strip().lower() != target:
            continue
        start = m.start()
        level = len(m.group(1))
        end = len(markdown)
        for j in range(i + 1, len(matches)):
            if len(matches[j].group(1)) <= level:
                end = matches[j].start()
                break
        return markdown[start:end].rstrip() + "\n"
    return ""


def _project(markdown: str, mode: str) -> dict[str, Any]:
    """Apply the ``mode`` projection to a Markdown body."""
    if mode == "outline":
        return {"mode": "outline", "outline": _make_outline(markdown)}
    if mode.startswith("sections:"):
        heading = mode.split(":", 1)[1]
        section = _extract_section(markdown, heading)
        return {
            "mode": mode,
            "heading": heading,
            "found": bool(section),
            "content": section,
        }
    return {"mode": "markdown", "content": markdown}


def _rendered_url(docs_base: str, source_path: str) -> str:
    """Map a ``docs/<path>`` source path back to its rendered URL."""
    inner = source_path[len("docs/"):] if source_path.startswith("docs/") else source_path
    inner = inner.removesuffix(".md")
    if inner == "index":
        inner = ""
    elif inner.endswith("/index"):
        inner = inner[: -len("/index")]
    base = docs_base.rstrip("/")
    if not inner:
        return f"{base}/"
    return f"{base}/{inner}/"


def register(mcp: FastMCP) -> None:
    """Register the fetch tool."""

    @mcp.tool()
    async def fetch_atlas_software_doc(
        url_or_path: str,
        mode: str = "markdown",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Fetch one ATLAS software docs page as Markdown from upstream GitLab.

        The repo is public; no auth required. Tries both
        ``docs/<path>/index.md`` and ``docs/<path>.md`` for directory-style
        inputs (MkDocs admits both). Falls through 404s.

        Args:
            url_or_path: Any of:
                - A rendered URL, e.g.
                  ``https://atlas-software.docs.cern.ch/analysis/grid/``
                - A relative path, e.g. ``analysis/grid/``
                - A direct ``.md`` source path, e.g. ``analysis/grid.md``
            mode: Output projection.
                - ``"markdown"`` (default): full body.
                - ``"outline"``: list of H1-H3 headings only - cheap way
                  to scout a long page.
                - ``"sections:<heading>"``: extract one section starting
                  from a matching heading (case-insensitive). E.g.
                  ``"sections:Build"``.
        """
        candidates = _candidate_source_paths(url_or_path)
        if not candidates:
            return format_error(
                ValueError(f"Could not derive a source path from {url_or_path!r}"),
                recovery=[
                    "Pass a URL like "
                    "https://atlas-software.docs.cern.ch/<path>/",
                    "or a relative path like 'athena/configuration/'.",
                    "Use search_atlas_software_docs(query=...) to find a "
                    "valid URL first.",
                ],
            )

        ctxd = ctx.request_context.lifespan_context
        http = ctxd["http"]
        gitlab_api: str = ctxd["gitlab_api"]
        project_id: str = ctxd["project_id"]
        docs_base: str = ctxd["docs_base"]

        last_error: Exception | None = None
        for path in candidates:
            api_url = (
                f"{gitlab_api.rstrip('/')}/projects/{project_id}/"
                f"repository/files/{quote(path, safe='')}/raw"
            )
            try:
                response = await http.get(api_url, params={"ref": "main"})
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
            if response.status_code == 404:
                continue
            try:
                response.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue

            markdown = response.text
            projection = _project(markdown, mode)
            return json.dumps(
                {
                    "source_path": path,
                    "url": _rendered_url(docs_base, path),
                    **projection,
                },
                default=str,
            )

        return format_error(
            last_error or FileNotFoundError("No matching source file"),
            recovery=[
                f"Tried {len(candidates)} candidate path(s) under "
                "docs/ - none resolved.",
                "Use search_atlas_software_docs(query=...) to find the "
                "correct URL first, then re-call fetch with that URL.",
            ],
        )
