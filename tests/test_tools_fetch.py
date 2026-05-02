"""Tests for ``fetch_doc``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from cern_mkdocs_mcp.tools.fetch import (
    _candidate_source_paths,
    _extract_section,
    _make_outline,
    _rendered_url,
    register,
)
from tests.conftest import capture_tools

SAMPLE_MD = """# Running on the grid

Submit jobs with prun.

## Build

Compile your work area first.

### Tags

Use a release tag.

## Submit

Then submit the job.
"""


class TestCandidatePaths:
    def test_url_with_trailing_slash(self) -> None:
        out = _candidate_source_paths(
            "https://atlas-software.docs.cern.ch/analysis/grid/",
        )
        assert out == ["docs/analysis/grid/index.md", "docs/analysis/grid.md"]

    def test_relative_path_with_trailing_slash(self) -> None:
        assert _candidate_source_paths("analysis/grid/") == [
            "docs/analysis/grid/index.md", "docs/analysis/grid.md",
        ]

    def test_relative_path_without_trailing_slash(self) -> None:
        assert _candidate_source_paths("analysis/grid") == [
            "docs/analysis/grid/index.md", "docs/analysis/grid.md",
        ]

    def test_md_path_passthrough(self) -> None:
        assert _candidate_source_paths("analysis/grid.md") == [
            "docs/analysis/grid.md",
        ]

    def test_strips_existing_docs_prefix(self) -> None:
        assert _candidate_source_paths("docs/analysis/grid.md") == [
            "docs/analysis/grid.md",
        ]

    def test_root_url(self) -> None:
        assert _candidate_source_paths(
            "https://atlas-software.docs.cern.ch/",
        ) == ["docs/index.md"]

    def test_empty(self) -> None:
        assert _candidate_source_paths("") == []
        assert _candidate_source_paths("   ") == []

    def test_drops_fragment(self) -> None:
        assert _candidate_source_paths(
            "https://atlas-software.docs.cern.ch/analysis/grid/#prun",
        ) == ["docs/analysis/grid/index.md", "docs/analysis/grid.md"]

    def test_drops_query(self) -> None:
        assert _candidate_source_paths("analysis/grid/?foo=bar") == [
            "docs/analysis/grid/index.md", "docs/analysis/grid.md",
        ]


class TestRenderedUrl:
    def test_index_md(self) -> None:
        assert (
            _rendered_url(
                "https://atlas-software.docs.cern.ch",
                "docs/analysis/grid/index.md",
            )
            == "https://atlas-software.docs.cern.ch/analysis/grid/"
        )

    def test_plain_md(self) -> None:
        assert (
            _rendered_url(
                "https://atlas-software.docs.cern.ch",
                "docs/analysis/grid.md",
            )
            == "https://atlas-software.docs.cern.ch/analysis/grid/"
        )

    def test_root(self) -> None:
        assert (
            _rendered_url(
                "https://atlas-software.docs.cern.ch", "docs/index.md",
            )
            == "https://atlas-software.docs.cern.ch/"
        )


class TestOutline:
    def test_h1_h2_h3_only(self) -> None:
        outline = _make_outline(SAMPLE_MD)
        levels = [(o["level"], o["heading"]) for o in outline]
        assert (1, "Running on the grid") in levels
        assert (2, "Build") in levels
        assert (3, "Tags") in levels
        assert (2, "Submit") in levels


class TestExtractSection:
    def test_extracts_named_section(self) -> None:
        body = _extract_section(SAMPLE_MD, "Build")
        assert body.startswith("## Build")
        assert "Compile your work area" in body
        # Stops before the next H2.
        assert "## Submit" not in body

    def test_case_insensitive(self) -> None:
        body = _extract_section(SAMPLE_MD, "build")
        assert body.startswith("## Build")

    def test_missing_returns_empty(self) -> None:
        assert _extract_section(SAMPLE_MD, "Doesn't Exist") == ""


class TestFetchTool:
    async def test_returns_full_markdown_by_default(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        result = await tools["fetch_doc"](
            "analysis/grid/", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["mode"] == "markdown"
        assert data["source"] == "atlas-sft"
        assert "Submit jobs with prun" in data["content"]
        assert data["url"].endswith("/analysis/grid/")
        assert data["source_path"] == "docs/analysis/grid/index.md"

    async def test_unknown_source_returns_recovery(
        self,
        mock_ctx: MagicMock,
    ) -> None:
        tools = capture_tools(register)
        result = await tools["fetch_doc"](
            "analysis/grid/", source="bogus", ctx=mock_ctx,
        )
        assert "Recovery steps" in result
        assert "atlas-sft" in result
        assert "batch" in result

    async def test_falls_through_404_to_alternate_candidate(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.side_effect = [
            make_response(status=404),
            make_response(text=SAMPLE_MD),
        ]
        tools = capture_tools(register)

        result = await tools["fetch_doc"](
            "analysis/grid/", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["source_path"] == "docs/analysis/grid.md"
        assert mock_http.get.call_count == 2

    async def test_outline_mode_returns_headings_only(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        result = await tools["fetch_doc"](
            "analysis/grid/", mode="outline", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["mode"] == "outline"
        levels = {(h["level"], h["heading"]) for h in data["outline"]}
        assert (1, "Running on the grid") in levels
        assert (2, "Build") in levels
        assert (2, "Submit") in levels
        assert (3, "Tags") in levels

    async def test_section_mode_extracts_one_section(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        result = await tools["fetch_doc"](
            "analysis/grid/", mode="sections:Build", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["found"] is True
        assert "Compile your work area" in data["content"]
        assert "Then submit the job" not in data["content"]

    async def test_section_mode_missing_heading_reports_not_found(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        result = await tools["fetch_doc"](
            "analysis/grid/", mode="sections:Nonexistent", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["found"] is False
        assert data["content"] == ""

    async def test_all_404_returns_recovery_pointing_at_search(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(status=404)
        tools = capture_tools(register)

        result = await tools["fetch_doc"](
            "nope/nada/", ctx=mock_ctx,
        )
        assert "Recovery steps" in result
        assert "search_docs" in result

    async def test_empty_input_returns_recovery(
        self,
        mock_ctx: MagicMock,
    ) -> None:
        tools = capture_tools(register)
        result = await tools["fetch_doc"]("", ctx=mock_ctx)
        assert "Could not derive" in result
        assert "Recovery steps" in result

    async def test_constructs_correct_gitlab_api_url_for_default_source(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        await tools["fetch_doc"](
            "analysis/grid.md", ctx=mock_ctx,
        )
        called_url = mock_http.get.call_args.args[0]
        # gitlab_project_path derived from repo_url (path-encoded, slashes → %2F)
        assert (
            "/projects/atlas%2Fsoftware-docs%2Fatlas-software-docs"
            "/repository/files/" in called_url
        )
        assert "docs%2Fanalysis%2Fgrid.md" in called_url
        assert called_url.endswith("/raw")
        assert mock_http.get.call_args.kwargs["params"] == {"ref": "main"}

    async def test_constructs_correct_gitlab_api_url_for_batch_source(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        await tools["fetch_doc"](
            "tutorial/intro.md", source="batch", ctx=mock_ctx,
        )
        called_url = mock_http.get.call_args.args[0]
        # gitlab_project_path for batch/batchdocs → batch%2Fbatchdocs
        assert "/projects/batch%2Fbatchdocs/repository/files/" in called_url
        assert "docs%2Ftutorial%2Fintro.md" in called_url

    async def test_rendered_url_uses_source_specific_docs_site(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        result = await tools["fetch_doc"](
            "tutorial/intro/", source="batch", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["source"] == "batch"
        assert data["url"] == "https://batchdocs.web.cern.ch/tutorial/intro/"

    async def test_missing_auth_returns_recovery(
        self,
        mock_ctx: MagicMock,
    ) -> None:
        """Auth-gated source without env var set returns a Recovery Guide."""
        tools = capture_tools(register)

        result = await tools["fetch_doc"](
            "analysis/grid/", source="atlas-computing", ctx=mock_ctx,
        )
        assert "Recovery steps" in result
        assert "DOCS_MCP_CERN_SSO_TOKEN" in result

    async def test_present_auth_passes_bearer_header(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
        monkeypatch: Any,
    ) -> None:
        """When the env var is set the Bearer token is forwarded to GitLab."""
        monkeypatch.setenv("DOCS_MCP_CERN_SSO_TOKEN", "test-sso-token")
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        await tools["fetch_doc"](
            "analysis/grid/", source="atlas-computing", ctx=mock_ctx,
        )
        called_headers = mock_http.get.call_args.kwargs.get("headers") or {}
        assert called_headers.get("Authorization") == "Bearer test-sso-token"

    async def test_public_source_sends_no_auth_header(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        """Public sources must not send an Authorization header."""
        mock_http.get.return_value = make_response(text=SAMPLE_MD)
        tools = capture_tools(register)

        await tools["fetch_doc"](
            "analysis/grid/", source="atlas-sft", ctx=mock_ctx,
        )
        # headers kwarg is either absent, None, or an empty dict
        called_headers = mock_http.get.call_args.kwargs.get("headers")
        assert not called_headers  # None or {}
