"""Tests for the GitBook (SUMMARY.md-walker) index backend."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from cern_mkdocs_mcp.tools._gitbook_index import (
    GitBookIndex,
    _normalize_summary_link,
    _parse_summary,
    _rendered_url,
    _section_of,
    _strip_markdown,
)

SAMPLE_SUMMARY = """# Summary

* [Introduction](README.md)
* [Overview](docs/overview.md)
   * [Features](docs/features.md)
       * [S3 Support](docs/s3_support.md)
* [Contact / Support](mailto:fts-support@cern.ch)
* [Upstream](https://example.com/external.md)
* [REST CLI](fts-rest/docs/cli/README.md)
"""

OVERVIEW_MD = """# Overview

FTS3 is a bulk data mover. Submit transfers via REST API.

```bash
fts-rest-transfer-submit -s https://example.org
```

See [features](features.md) for the feature list.
"""

FEATURES_MD = "# Features\n\nList of features including third party copies."

S3_MD = "# S3 Support\n\nNotes on S3 endpoint configuration."

README_MD = "# Introduction\n\nFile Transfer Service top-level overview."


class TestStripMarkdown:
    def test_drops_code_fences(self) -> None:
        out = _strip_markdown("text\n```\ncode\n```\nmore")
        assert "code" not in out
        assert "text" in out
        assert "more" in out

    def test_unwraps_links(self) -> None:
        out = _strip_markdown("see [the docs](https://example.com)")
        assert "the docs" in out
        assert "https://example.com" not in out

    def test_drops_inline_code(self) -> None:
        out = _strip_markdown("call `fts-rest-whoami` then check")
        assert "fts-rest-whoami" not in out
        assert "call" in out
        assert "check" in out

    def test_drops_heading_markers(self) -> None:
        out = _strip_markdown("# Heading\n## Sub")
        assert "#" not in out


class TestNormalizeSummaryLink:
    def test_relative_md(self) -> None:
        assert _normalize_summary_link("docs/overview.md") == "docs/overview.md"

    def test_drops_anchor(self) -> None:
        assert (
            _normalize_summary_link("docs/overview.md#section")
            == "docs/overview.md"
        )

    def test_strips_leading_slash(self) -> None:
        assert _normalize_summary_link("/docs/x.md") == "docs/x.md"

    def test_skips_external_http(self) -> None:
        assert _normalize_summary_link("https://example.com/x.md") is None

    def test_skips_mailto(self) -> None:
        assert _normalize_summary_link("mailto:user@example.com") is None

    def test_skips_non_md(self) -> None:
        assert _normalize_summary_link("docs/image.png") is None
        assert _normalize_summary_link("docs/overview.html") is None

    def test_skips_anchor_only(self) -> None:
        assert _normalize_summary_link("#section") is None

    def test_empty_returns_none(self) -> None:
        assert _normalize_summary_link("") is None
        assert _normalize_summary_link("   ") is None


class TestParseSummary:
    def test_extracts_md_links_in_order(self) -> None:
        entries = _parse_summary(SAMPLE_SUMMARY)
        paths = [p for _, p in entries]
        assert paths[0] == "README.md"
        assert "docs/overview.md" in paths
        assert "docs/features.md" in paths
        assert "docs/s3_support.md" in paths

    def test_filters_external_and_mailto(self) -> None:
        entries = _parse_summary(SAMPLE_SUMMARY)
        paths = [p for _, p in entries]
        assert all(not p.startswith("http") for p in paths)
        assert all(not p.startswith("mailto") for p in paths)

    def test_keeps_cross_repo_paths(self) -> None:
        """Cross-repo links like fts-rest/docs/... are not filtered here;
        they will silently 404 at fetch time and be dropped from the corpus.
        """
        entries = _parse_summary(SAMPLE_SUMMARY)
        paths = [p for _, p in entries]
        assert "fts-rest/docs/cli/README.md" in paths

    def test_deduplicates_by_path(self) -> None:
        summary = "* [A](x.md)\n* [B](x.md)\n"
        entries = _parse_summary(summary)
        assert len(entries) == 1
        assert entries[0] == ("A", "x.md")


class TestRenderedUrl:
    def test_readme_at_root(self) -> None:
        assert (
            _rendered_url(
                "https://fts3-docs.web.cern.ch/fts3-docs", "README.md",
            )
            == "https://fts3-docs.web.cern.ch/fts3-docs/index.html"
        )

    def test_nested_readme(self) -> None:
        assert (
            _rendered_url(
                "https://fts3-docs.web.cern.ch/fts3-docs",
                "docs/install/README.md",
            )
            == "https://fts3-docs.web.cern.ch/fts3-docs/docs/install/index.html"
        )

    def test_regular_md(self) -> None:
        assert (
            _rendered_url(
                "https://fts3-docs.web.cern.ch/fts3-docs", "docs/overview.md",
            )
            == "https://fts3-docs.web.cern.ch/fts3-docs/docs/overview.html"
        )


class TestSectionOf:
    def test_root_readme(self) -> None:
        assert _section_of("README.md") == ""

    def test_top_level_only(self) -> None:
        assert _section_of("overview.md") == ""

    def test_first_segment(self) -> None:
        assert _section_of("docs/install/quick.md") == "docs"


class TestGitBookIndex:
    @pytest.fixture
    def index(self) -> GitBookIndex:
        return GitBookIndex(
            repo_path="fts/documentation",
            docs_site_url="https://fts3-docs.web.cern.ch/fts3-docs",
            gitlab_api="https://gitlab.cern.ch/api/v4",
            summary_path="SUMMARY.md",
            default_branch="master",
        )

    def _wire_responses(
        self,
        mock_http: MagicMock,
        make_response: Any,
        *,
        include_cross_repo: bool = True,
    ) -> None:
        """Map GitLab Files-API URLs to mock responses by path."""

        def _by_path(url: str, **_: Any) -> Any:
            if "SUMMARY.md" in url:
                return make_response(text=SAMPLE_SUMMARY)
            if "README.md" in url and "fts-rest" not in url:
                return make_response(text=README_MD)
            if "docs%2Foverview.md" in url:
                return make_response(text=OVERVIEW_MD)
            if "docs%2Ffeatures.md" in url:
                return make_response(text=FEATURES_MD)
            if "docs%2Fs3_support.md" in url:
                return make_response(text=S3_MD)
            if "fts-rest" in url:
                # Cross-repo link silently 404s.
                return make_response(status=404) if include_cross_repo else make_response(text="")
            return make_response(status=404)

        mock_http.get.side_effect = _by_path

    async def test_refresh_walks_summary_and_indexes_pages(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        self._wire_responses(mock_http, make_response)
        await index.refresh(mock_http)
        assert index.is_loaded
        # 4 indexed: README, overview, features, s3_support; fts-rest 404s.
        paths = {d["source_path"] for d in index.docs}
        assert paths == {
            "README.md", "docs/overview.md",
            "docs/features.md", "docs/s3_support.md",
        }

    async def test_search_returns_bm25_ranked_hits(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        self._wire_responses(mock_http, make_response)
        await index.refresh(mock_http)
        results = index.search("s3 endpoint", limit=5, section=None)
        assert results
        # S3 page must rank top for "s3 endpoint".
        assert "s3_support" in results[0]["path"]
        assert results[0]["url"].endswith("/docs/s3_support.html")
        assert results[0]["snippet"]

    async def test_search_filter_by_section(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        self._wire_responses(mock_http, make_response)
        await index.refresh(mock_http)
        results = index.search("party", limit=10, section="docs")
        # Only docs/* pages should appear.
        assert all(r["section"] == "docs" for r in results)

    async def test_search_before_refresh_returns_empty(
        self, index: GitBookIndex,
    ) -> None:
        assert index.search("anything", limit=5, section=None) == []

    async def test_empty_query_returns_empty(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        self._wire_responses(mock_http, make_response)
        await index.refresh(mock_http)
        assert index.search("", limit=5, section=None) == []
        assert index.search("   ", limit=5, section=None) == []

    async def test_ensure_fresh_caches_within_ttl(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        self._wire_responses(mock_http, make_response)
        await index.ensure_fresh(mock_http)
        first_calls = mock_http.get.call_count
        await index.ensure_fresh(mock_http)
        # Still fresh: no extra fetches.
        assert mock_http.get.call_count == first_calls

    async def test_ensure_fresh_reloads_when_stale(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        self._wire_responses(mock_http, make_response)
        await index.ensure_fresh(mock_http)
        first_calls = mock_http.get.call_count
        index.fetched_at = 0
        await index.ensure_fresh(mock_http)
        assert mock_http.get.call_count > first_calls

    async def test_refresh_uses_default_branch_param(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        self._wire_responses(mock_http, make_response)
        await index.refresh(mock_http)
        # Every call must have ref=master in params.
        for call in mock_http.get.call_args_list:
            assert call.kwargs.get("params") == {"ref": "master"}

    async def test_refresh_when_summary_missing_leaves_index_empty(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.side_effect = lambda *a, **kw: make_response(status=404)
        await index.refresh(mock_http)
        assert not index.is_loaded
        assert index.docs == []
        # fetched_at still advances to avoid hammering.
        assert index.fetched_at > 0
        assert not index.is_stale

    async def test_passes_auth_headers_through(
        self,
        index: GitBookIndex,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        self._wire_responses(mock_http, make_response)
        await index.refresh(mock_http, headers={"Authorization": "Bearer t"})
        for call in mock_http.get.call_args_list:
            assert call.kwargs.get("headers", {}).get("Authorization") == "Bearer t"


class TestStaleness:
    async def test_after_refresh_is_fresh(
        self,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        idx = GitBookIndex(
            repo_path="fts/documentation",
            docs_site_url="https://fts3-docs.web.cern.ch/fts3-docs",
            gitlab_api="https://gitlab.cern.ch/api/v4",
            default_branch="master",
        )
        mock_http.get.side_effect = lambda *a, **kw: make_response(text=SAMPLE_SUMMARY)
        await idx.refresh(mock_http)
        assert not idx.is_stale
        assert idx.fetched_at <= time.time()
