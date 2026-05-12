"""BM25 index over a legacy GitBook (v2 / CLI) documentation source.

Legacy GitBook sites do not publish a ``search_index.json`` — their
in-browser search is driven by ``gitbook-plugin-lunr`` against a Lunr
index that isn't always served at a stable URL. To get a queryable
server-side corpus we walk ``SUMMARY.md`` (the GitBook table of
contents) to discover every ``.md`` page, fetch each one from the
GitLab Files API, and build an in-memory BM25 ranker.

URL convention (GitBook 3.x.x output):

  source path                            rendered URL
  -----------                            ------------
  README.md                              <docs_site_url>/index.html
  docs/overview.md                       <docs_site_url>/docs/overview.html
  docs/install/quick.md                  <docs_site_url>/docs/install/quick.html

i.e. source paths render 1-to-1 with ``.md → .html`` — no directory
stripping (unlike MkDocs).

External links in SUMMARY.md (``http(s)://``, ``mailto:``) and links to
markdown files outside the indexed repo (e.g. ``fts-rest/docs/...``
which the FTS docs build pulls in via a build-time script from a
different repo) are skipped silently — they are not in our corpus.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlparse

from rank_bm25 import BM25Okapi

from cern_mkdocs_mcp.tools._index import (
    TTL_SECONDS,
    _make_snippet,
    _tokenize,
)

if TYPE_CHECKING:
    import httpx

_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
_EMPHASIS_RE = re.compile(r"[*_]{1,3}")
_FETCH_CONCURRENCY = 8


def _strip_markdown(md: str) -> str:
    """Cheap Markdown → plain text for snippet extraction.

    Drops code fences, inline code, heading markers, emphasis markers,
    and rewrites ``[text](url)`` to ``text``. The BM25 ranker is
    tolerant of leftover punctuation; this is just enough to keep
    snippets readable.
    """
    md = _CODE_FENCE_RE.sub(" ", md)
    md = _INLINE_CODE_RE.sub(" ", md)
    md = _LINK_RE.sub(r"\1", md)
    md = _HEADING_RE.sub("", md)
    md = _EMPHASIS_RE.sub("", md)
    return md


def _normalize_summary_link(target: str) -> str | None:
    """Return the cleaned source path of a SUMMARY.md link, or ``None``.

    Drops anchors and query strings. Returns ``None`` for external links
    (any URL with a scheme), ``mailto:`` links, or non-``.md`` targets.
    """
    target = target.strip()
    if not target:
        return None
    if target.startswith(("http://", "https://", "mailto:", "ftp://", "#")):
        return None
    parsed = urlparse(target)
    if parsed.scheme:  # any other scheme we didn't enumerate above
        return None
    path = parsed.path.strip()
    if not path:
        return None
    # Drop fragment/query already handled by urlparse via .path
    if not path.endswith(".md"):
        return None
    # Strip a leading slash to keep paths relative to repo root.
    return path.lstrip("/")


def _parse_summary(summary_md: str) -> list[tuple[str, str]]:
    """Extract ``(title, source_path)`` pairs from a SUMMARY.md body.

    Deduplicates by source path while preserving SUMMARY order (the
    first title wins). Skips external links and non-``.md`` targets.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _LINK_RE.finditer(summary_md):
        title = m.group(1).strip()
        path = _normalize_summary_link(m.group(2))
        if path is None or path in seen:
            continue
        seen.add(path)
        out.append((title, path))
    return out


def _rendered_url(docs_site_url: str, source_path: str) -> str:
    """Map a GitBook source path back to its rendered URL.

    ``README.md`` becomes ``<docs_site_url>/index.html``; any other
    ``foo/bar.md`` becomes ``<docs_site_url>/foo/bar.html``.
    """
    base = docs_site_url.rstrip("/")
    if source_path == "README.md":
        return f"{base}/index.html"
    if source_path.endswith("/README.md"):
        inner = source_path[: -len("README.md")] + "index.html"
        return f"{base}/{inner}"
    if source_path.endswith(".md"):
        inner = source_path[: -len(".md")] + ".html"
        return f"{base}/{inner}"
    return f"{base}/{source_path}"


def _section_of(source_path: str) -> str:
    """First path segment of a source path (``""`` for repo root)."""
    head = source_path.strip("/")
    if not head or head == "README.md":
        return ""
    parts = head.split("/", 1)
    if len(parts) == 1:
        # e.g. "overview.md" -> "" (no folder); GitBook sites often have
        # most pages under a top-level dir like "docs/" so this is rare.
        return ""
    return parts[0]


def _file_api_url(gitlab_api: str, project_path: str, file_path: str) -> str:
    """Build a GitLab Files-API raw URL for one repo file."""
    return (
        f"{gitlab_api.rstrip('/')}/projects/{quote(project_path, safe='')}/"
        f"repository/files/{quote(file_path, safe='')}/raw"
    )


class GitBookIndex:
    """BM25 index over the markdown referenced by a GitBook SUMMARY.md.

    Mirrors the interface of :class:`cern_mkdocs_mcp.tools._index.DocsIndex`:
    ``ensure_fresh(http, *, headers=None)`` and ``search(query, *, limit,
    section)`` so that the search tool can treat both backends
    polymorphically.
    """

    def __init__(
        self,
        *,
        repo_path: str,
        docs_site_url: str,
        gitlab_api: str,
        summary_path: str = "SUMMARY.md",
        default_branch: str = "master",
    ) -> None:
        """Initialize the index.

        Args:
            repo_path: GitLab project path (e.g. ``"fts/documentation"``),
                raw (not URL-encoded).
            docs_site_url: Public URL of the rendered GitBook site.
            gitlab_api: GitLab API base, e.g.
                ``"https://gitlab.cern.ch/api/v4"``.
            summary_path: Path to the SUMMARY.md within the repo.
            default_branch: Git ref to fetch from. GitBook FTS docs are
                on ``master``.
        """
        self.repo_path = repo_path
        self.docs_site_url = docs_site_url.rstrip("/")
        self.gitlab_api = gitlab_api.rstrip("/")
        self.summary_path = summary_path
        self.default_branch = default_branch
        self.docs: list[dict[str, Any]] = []
        self.bm25: BM25Okapi | None = None
        self.fetched_at: float = 0.0

    @property
    def is_stale(self) -> bool:
        return (time.time() - self.fetched_at) > TTL_SECONDS

    @property
    def is_loaded(self) -> bool:
        return self.bm25 is not None

    async def _fetch_raw(
        self,
        http: httpx.AsyncClient,
        path: str,
        headers: dict[str, str] | None,
    ) -> str | None:
        """Fetch one file's raw content. ``None`` on 404 or transport error."""
        url = _file_api_url(self.gitlab_api, self.repo_path, path)
        try:
            response = await http.get(
                url,
                params={"ref": self.default_branch},
                headers=headers or None,
            )
        except Exception:  # noqa: BLE001
            return None
        if response.status_code == 404:
            return None
        try:
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            return None
        return response.text

    async def refresh(
        self,
        http: httpx.AsyncClient,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Walk SUMMARY.md, fetch every ``.md`` it lists, build BM25."""
        summary = await self._fetch_raw(http, self.summary_path, headers)
        if summary is None:
            # Leave bm25 None; ``fetched_at`` advances to avoid hammering.
            self.docs = []
            self.bm25 = None
            self.fetched_at = time.time()
            return

        entries = _parse_summary(summary)

        sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

        async def _one(title: str, path: str) -> dict[str, Any] | None:
            async with sem:
                body = await self._fetch_raw(http, path, headers)
            if body is None:
                return None
            plain = _strip_markdown(body)
            return {
                "title": title,
                "source_path": path,
                "url": _rendered_url(self.docs_site_url, path),
                "section": _section_of(path),
                "text": plain,
            }

        results = await asyncio.gather(
            *(_one(t, p) for t, p in entries),
        )
        kept: list[dict[str, Any]] = []
        corpora: list[list[str]] = []
        for doc in results:
            if doc is None:
                continue
            tokens = _tokenize(f"{doc['title']} {doc['text']}")
            if not tokens:
                continue
            kept.append(doc)
            corpora.append(tokens)

        self.docs = kept
        self.bm25 = BM25Okapi(corpora) if corpora else None
        self.fetched_at = time.time()

    async def ensure_fresh(
        self,
        http: httpx.AsyncClient,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Refresh the index if missing or stale (older than 24 h)."""
        if not self.is_loaded or self.is_stale:
            await self.refresh(http, headers=headers)

    def search(
        self,
        query: str,
        *,
        limit: int,
        section: str | None,
    ) -> list[dict[str, Any]]:
        """Return up to ``limit`` BM25-ranked hits, optionally section-filtered.

        Each hit carries ``{title, url, path, section, score, snippet}``,
        matching :meth:`DocsIndex.search` so the tool layer is agnostic.
        """
        if self.bm25 is None:
            return []
        tokens = _tokenize(query)
        if not tokens:
            return []

        scores = self.bm25.get_scores(tokens)
        order = sorted(
            range(len(scores)), key=lambda i: float(scores[i]), reverse=True,
        )

        section_lc = section.lower() if section else None
        results: list[dict[str, Any]] = []
        for idx in order:
            score = float(scores[idx])
            if score <= 0:
                break
            doc = self.docs[idx]
            if section_lc is not None and doc["section"].lower() != section_lc:
                continue
            results.append({
                "title": doc["title"] or "(untitled)",
                "url": doc["url"],
                "path": doc["source_path"],
                "section": doc["section"],
                "score": round(score, 3),
                "snippet": _make_snippet(doc["text"], tokens),
            })
            if len(results) >= limit:
                break
        return results
