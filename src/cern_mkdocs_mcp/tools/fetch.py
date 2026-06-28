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


def _candidate_source_paths(
    url_or_path: str,
    docs_site_url: str = "",
) -> list[str]:
    """Map a docs URL or relative path to candidate ``docs/...`` paths.

    MkDocs convention only. For GitBook sources see
    :func:`_candidate_gitbook_paths`.

    Handles three input shapes:
    - Rendered URL: ``https://example.docs.cern.ch/analysis/grid/``
    - Relative path: ``analysis/grid/`` or ``/analysis/grid/``
    - Direct .md path: ``analysis/grid.md`` (with or without ``docs/`` prefix)

    For directory-style inputs ``foo/bar/`` we return both ``foo/bar/index.md``
    (the MkDocs convention) and ``foo/bar.md`` (the alternative MkDocs
    convention). The tool tries them in order and falls through 404s.

    ``docs_site_url`` lets the resolver strip a versioned-site base path from a
    rendered URL — e.g. a ``mike`` version segment like ``/latest`` (or a
    longer prefix such as ``/fastframesdocumentation/latest``) that the
    published URL carries but the repo source tree does not. For unversioned
    sites ``docs_site_url`` has no path component, so the strip is a no-op and
    behaviour is unchanged. Only applied to full URLs (with a scheme); relative
    inputs are assumed already doc-relative. Mirrors the GitBook branch's
    ``site_base`` handling.
    """
    raw = url_or_path.strip()
    if not raw:
        return []
    parsed = urlparse(raw)
    if parsed.scheme:
        path = parsed.path
        site_base = urlparse(docs_site_url).path.rstrip("/")
        if site_base and path.startswith(site_base + "/"):
            path = path[len(site_base):]
        elif site_base and path == site_base:
            path = ""
    else:
        path = raw
    path = path.split("#", 1)[0].split("?", 1)[0]
    path = path.strip("/")
    if path.startswith("docs/"):
        path = path[len("docs/"):]
    if not path:
        return ["docs/index.md"]
    if path.endswith(".md"):
        return [f"docs/{path}"]
    return [f"docs/{path}/index.md", f"docs/{path}.md"]


def _candidate_gitbook_paths(
    url_or_path: str,
    docs_site_url: str,
) -> list[str]:
    """Map a GitBook URL or path to candidate source ``.md`` paths.

    GitBook output is 1-to-1 with source: ``foo/bar.md`` renders as
    ``foo/bar.html``; ``README.md`` at any level renders as
    ``index.html`` for that directory.

    Handles three input shapes:
    - Rendered URL: ``https://fts3-docs.web.cern.ch/fts3-docs/docs/overview.html``
    - Relative path: ``docs/overview.html`` or ``docs/overview.md``
    - Repo-root README: ``index.html``, empty string, or just the site URL
    """
    raw = url_or_path.strip()
    if not raw:
        return []
    parsed = urlparse(raw)
    if parsed.scheme:
        path = parsed.path
    else:
        path = raw
    path = path.split("#", 1)[0].split("?", 1)[0]

    # If the URL had a scheme, strip any GitBook docs_site_url base path
    # (e.g. "/fts3-docs/") so we're left with the doc-relative portion.
    if parsed.scheme:
        site_base = urlparse(docs_site_url).path.rstrip("/")
        if site_base and path.startswith(site_base + "/"):
            path = path[len(site_base):]
        elif site_base and path == site_base:
            path = ""

    path = path.strip("/")
    if not path or path == "index.html":
        return ["README.md"]
    if path.endswith("/index.html"):
        inner = path[: -len("/index.html")]
        return [f"{inner}/README.md"]
    if path.endswith(".html"):
        return [path[: -len(".html")] + ".md"]
    if path.endswith(".md"):
        return [path]
    # Bare directory like "docs/install/" — GitBook directories don't
    # render to .html, so the most likely meaning is the README in that
    # directory.
    return [f"{path}/README.md"]


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
    """Map a ``docs/<path>`` source path back to its rendered URL (MkDocs)."""
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


def _rendered_url_gitbook(docs_base: str, source_path: str) -> str:
    """Map a GitBook ``.md`` source path back to its rendered URL."""
    base = docs_base.rstrip("/")
    if source_path == "README.md":
        return f"{base}/index.html"
    if source_path.endswith("/README.md"):
        inner = source_path[: -len("README.md")] + "index.html"
        return f"{base}/{inner}"
    if source_path.endswith(".md"):
        return f"{base}/{source_path[: -len('.md')]}.html"
    return f"{base}/{source_path}"


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
                ``batch``, ``cloud``, ``ml``, ``swan``, ``fts``,
                ``fastframes``, ``topcptoolkit``.
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

        if source_obj.source_type == "gitbook":
            candidates = _candidate_gitbook_paths(
                url_or_path, source_obj.docs_site_url,
            )
            render_url = _rendered_url_gitbook
        else:
            candidates = _candidate_source_paths(
                url_or_path, source_obj.docs_site_url,
            )
            render_url = _rendered_url

        if not candidates:
            return format_error(
                ValueError(f"Could not derive a source path from {url_or_path!r}"),
                recovery=[
                    "Pass a URL like https://example.docs.cern.ch/<path>/",
                    "or a relative path like 'athena/configuration/'.",
                    "Use search_docs(query=..., source=...) to find a valid URL first.",
                ],
            )

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
                    params={"ref": source_obj.default_branch},
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
                    "url": render_url(source_obj.docs_site_url, path),
                    **projection,
                },
                default=str,
            )

        return format_error(
            last_error or FileNotFoundError("No matching source file"),
            recovery=[
                f"Tried {len(candidates)} candidate path(s) - none resolved.",
                "Use search_docs(query=..., source=...) to find the correct URL first, "
                "then re-call fetch with that URL.",
            ],
        )
