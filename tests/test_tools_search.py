"""Tests for ``search_atlas_software_docs``."""

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

        result = await tools["search_atlas_software_docs"](
            query="athena configuration", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["query"] == "athena configuration"
        assert data["returned"] >= 1
        top = data["results"][0]
        assert "athena" in top["url"].lower()
        assert top["snippet"]
        assert data["hint"] is None
        assert data["next_action"] and "fetch_atlas_software_doc" in data["next_action"]

    async def test_unknown_section_returns_recovery_listing_valid_sections(
        self, mock_ctx: MagicMock,
    ) -> None:
        tools = capture_tools(register)
        result = await tools["search_atlas_software_docs"](
            query="anything", section="bogus", ctx=mock_ctx,
        )
        assert "Recovery steps" in result
        # Mentions the valid section names.
        assert "athena" in result
        assert "analysis" in result

    async def test_section_filter_applied(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        result = await tools["search_atlas_software_docs"](
            query="grid", section="analysis", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["section"] == "analysis"
        assert data["results"]
        assert all(r["section"] == "analysis" for r in data["results"])

    async def test_empty_results_includes_hint(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        result = await tools["search_atlas_software_docs"](
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

        result = await tools["search_atlas_software_docs"](
            query="athena", ctx=mock_ctx,
        )
        assert "network down" in result
        assert "Recovery steps" in result

    async def test_limit_clamped(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        result = await tools["search_atlas_software_docs"](
            query="athena", limit=500, ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["limit"] == 25  # _MAX_LIMIT

    async def test_section_normalized(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        result = await tools["search_atlas_software_docs"](
            query="grid", section="  ANALYSIS  ", ctx=mock_ctx,
        )
        data = json.loads(result)
        assert data["section"] == "analysis"

    async def test_index_loaded_only_once_across_calls(
        self,
        mock_ctx: MagicMock,
        mock_http: MagicMock,
        make_response: Any,
    ) -> None:
        mock_http.get.return_value = make_response(json_data=SAMPLE_PAYLOAD)
        tools = capture_tools(register)

        await tools["search_atlas_software_docs"](query="athena", ctx=mock_ctx)
        await tools["search_atlas_software_docs"](query="grid", ctx=mock_ctx)
        # The MkDocs payload is downloaded exactly once thanks to the TTL
        # cache on DocsIndex.
        assert mock_http.get.call_count == 1
