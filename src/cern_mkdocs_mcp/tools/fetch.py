"""``fetch_doc`` - retrieve one page as Markdown from a documentation source.

Hits the GitLab Files Raw API for the docs source repo. Repos are public;
no token needed.

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

from cern_mkdocs_mcp.config import (
    MissingAuthError,
    format_sources_guide,
    resolve_auth_headers,
    validate_source_id,
)
from cern_mkdocs_mcp.tools._helpers import format_error

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_OUTLINE_MAX_LEVEL = 3


def _candidate_source_paths(url_or_path: str) -> list[str]:
    """Map a docs URL or relative path to candidate ``docs/...`` paths.

    Handles three input shapes:
    - Rendered URL: ``https://example.docs.cern.ch/analysis/grid/``
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
    async def fetch_doc(
        url_or_path: str,
        source: str = "atlas-sft",
        mode: str = "markdown",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Fetch one documentation page as Markdown from upstream VCS.

        Public sources need no credentials. Auth-gated sources (e.g.
        ``atlas-computing``, ``atlas-databases``) require the appropriate
        environment variable to be set (see ``docs://sources``).

        Tries both ``docs/<path>/index.md`` and ``docs/<path>.md`` for
        directory-style inputs (MkDocs admits both). Falls through 404s.

        Args:
            url_or_path: Any of:
                - A rendered URL, e.g.
                  ``https://atlas-software.docs.cern.ch/analysis/grid/``
                - A relative path, e.g. ``analysis/grid/``
                - A direct ``.md`` source path, e.g. ``analysis/grid.md``
            source: Documentation source ID. One of:
                ``atlas-sft``, ``atlas-computing``, ``atlas-databases``,
                ``batch``, ``cloud``, ``ml``, ``swan``.
                Default: ``atlas-sft`` (ATLAS Software).
            mode: Output projection.
                - ``"markdown"`` (default): full body.
                - ``"outline"``: list of H1-H3 headings only - cheap way
                  to scout a long page.
                - ``"sections:<heading>"``: extract one section starting
                  from a matching heading (case-insensitive). E.g.
                  ``"sections:Build"``.
        """
        source_norm = source.strip().lower() if source else "atlas-sft"
        candidates = _candidate_source_paths(url_or_path)
        if not candidates:
            return format_error(
                ValueError(f"Could not derive a source path from {url_or_path!r}"),
                recovery=[
                    "Pass a URL like https://example.docs.cern.ch/<path>/",
                    "or a relative path like 'athena/configuration/'.",
                    "Use search_docs(query=..., source=...) to find a valid URL first.",
                ],
            )

        ctxd = ctx.request_context.lifespan_context
        http = ctxd["http"]
        gitlab_api: str = ctxd["gitlab_api"]
        sources_registry = ctxd["sources"]

        # Validate source ID
        try:
            validate_source_id(source_norm, sources_registry)
        except ValueError as e:
            return format_error(e, recovery=[
                format_sources_guide(sources_registry),
            ])

        source_obj = sources_registry[source_norm]

        try:
            auth_headers = resolve_auth_headers(source_obj)
        except MissingAuthError as exc:
            return format_error(exc, recovery=[
                f"Set the environment variable ${exc.env_var} to a valid "
                "CERN SSO token before fetching from this source.",
                "Public sources (no auth required): "
                + ", ".join(
                    s.id for s in sources_registry.values() if s.auth is None
                ),
            ])

        project_path = quote(source_obj.gitlab_project_path, safe="")
        last_error: Exception | None = None
        for path in candidates:
            api_url = (
                f"{gitlab_api.rstrip('/')}/projects/{project_path}/"
                f"repository/files/{quote(path, safe='')}/raw"
            )
            try:
                response = await http.get(
                    api_url,
                    params={"ref": "main"},
                    headers=auth_headers or None,
                )
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
                    "source": source_norm,
                    "source_path": path,
                    "url": _rendered_url(source_obj.docs_site_url, path),
                    **projection,
                },
                default=str,
            )

        return format_error(
            last_error or FileNotFoundError("No matching source file"),
            recovery=[
                f"Tried {len(candidates)} candidate path(s) under docs/ - none resolved.",
                "Use search_docs(query=..., source=...) to find the correct URL first, "
                "then re-call fetch with that URL.",
            ],
        )
