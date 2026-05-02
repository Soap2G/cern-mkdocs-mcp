"""Tests for ``search_docs``."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from atlas_software_docs_mcp.tools.search import register
from tests.conftest import capture_tools

SAMPLE_PAYLOAD = {
    "docs": [
        {
            "location": "athena/configuration/",
            "title": "Athena configuration",
            "text": (
                "Configuring jobs in Athena uses the ComponentAccumulator "
                "API."
            ),
        },
        {
            "location": "analysis/grid/",
            "title": "Running on the grid",
            "text": "Submit analysis jobs to the WLCG grid via prun.",
        },
        # Decoy: present so single-doc terms ("athena", "grid") have
        # df < N/2, which keeps their BM25 IDF strictly positive. With
        # only two docs, df=1 yields IDF = log(1.5/1.5) = 0 and the
        # search would return nothing (DocsIndex.search filters score>0).
        {
            "location": "developers/git/",
            "title": "Git workflow",
            "text": "Use feature branches and merge requests for code review.",
        },
    ],
}


class TestSearchTool:
    async def test_loads_index_and_returns_hits(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        result = await tools["search_docs"](
            query="athena configuration", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["query"] == "athena configuration"
        assert data["source"] == "atlas-sft"  # default
        assert data["returned"] >= 1
        top = data["results"][0]
        assert "athena" in top["url"].lower()
        assert top["snippet"]
        assert data["hint"] is None
        assert data["next_action"] and "fetch_doc" in data["next_action"]

    async def test_unknown_source_returns_recovery_listing_valid_sources(
        self, mock_ctx: MagicMock,
    ) -> None:
        tools = capture_tools(register)
        result = await tools["search_docs"](
            query="anything", source="bogus-not-registered", ctx=mock_ctx,
        )
        assert "Recovery steps" in result
        # Mentions valid sources from the sample registry.
        assert "atlas-sft" in result
        assert "batch" in result

    async def test_routes_to_correct_source(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data={
            "docs": [
                {
                    "location": "tutorial/condor_submit/",
                    "title": "condor_submit tutorial",
                    "text": "Submit a HTCondor job with condor_submit.",
                },
                {
                    "location": "advanced/scheduling/",
                    "title": "scheduling",
                    "text": "Configure scheduling priorities for fair use.",
                },
                {
                    "location": "extras/security/",
                    "title": "security",
                    "text": "Tokens secure jobs across pools.",
                },
            ],
        })
        tools = capture_tools(register)

        result = await tools["search_docs"](
            query="condor", source="batch", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["source"] == "batch"
        # The URL of any hit must come from the batch source's docs_site.
        for hit in data["results"]:
            assert hit["url"].startswith("https://batchdocs.web.cern.ch/")
        # The URL the index downloaded from is the batch source's payload.
        called_url = mock_http.get.call_args.args[0]
        assert called_url == "https://batchdocs.web.cern.ch/search/search_index.json"

    async def test_empty_results_includes_hint(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        result = await tools["search_docs"](
            query="zzzzzzz_nomatch", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["returned"] == 0
        assert data["hint"]
        assert data["next_action"] is None

    async def test_index_load_failure_returns_recovery(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
    ) -> None:
        mock_http.get.side_effect = RuntimeError("network down")
        tools = capture_tools(register)

        result = await tools["search_docs"](
            query="athena", ctx=mock_ctx,
        )
        assert "network down" in result
        assert "Recovery steps" in result
        # Recovery message names the affected source's site.
        assert "atlas-software.docs.cern.ch" in result

    async def test_limit_clamped(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        result = await tools["search_docs"](
            query="athena", limit=500, ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["limit"] == 25  # _MAX_LIMIT

    async def test_index_loaded_only_once_across_calls_per_source(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        await tools["search_docs"](query="athena", ctx=mock_ctx)
        await tools["search_docs"](query="grid", ctx=mock_ctx)
        # Same source -> the MkDocs payload is downloaded exactly once
        # thanks to DocsIndex's TTL cache.
        assert mock_http.get.call_count == 1

    async def test_each_source_loads_its_own_index(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        await tools["search_docs"](
            query="athena", source="atlas-sft", ctx=mock_ctx,
        )
        await tools["search_docs"](
            query="condor", source="batch", ctx=mock_ctx,
        )
        # One fetch per source.
        assert mock_http.get.call_count == 2
        called_urls = {c.args[0] for c in mock_http.get.call_args_list}
        assert called_urls == {
            "https://atlas-software.docs.cern.ch/search/search_index.json",
            "https://batchdocs.web.cern.ch/search/search_index.json",
        }

    async def test_missing_auth_returns_recovery(
        self,
        mock_ctx: MagicMock,
    ) -> None:
        """Auth-gated source without env var set returns a Recovery Guide."""
        tools = capture_tools(register)

        result = await tools["search_docs"](
            query="athena", source="atlas-computing", ctx=mock_ctx,
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
        """When the env var is set the Bearer token reaches the HTTP call."""
        monkeypatch.setenv("DOCS_MCP_CERN_SSO_TOKEN", "test-sso-token")
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        await tools["search_docs"](
            query="athena", source="atlas-computing", ctx=mock_ctx,
        )
        called_headers = mock_http.get.call_args.kwargs.get("headers") or {}
        assert called_headers.get("Authorization") == "Bearer test-sso-token"
