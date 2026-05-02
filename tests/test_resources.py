"""Tests for MCP resource registration."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from atlas_software_docs_mcp.config import DocSource
from atlas_software_docs_mcp.resources import register


def _capture_resource(mcp: MagicMock) -> list[dict[str, Any]]:
    """Replace ``mcp.resource`` with a recorder; return the captured calls."""
    captured: list[dict[str, Any]] = []

    def resource_decorator(
        uri: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
    ) -> Any:
        def decorator(func: Any) -> Any:
            captured.append({
                "uri": uri,
                "name": name,
                "description": description,
                "mime_type": mime_type,
                "func": func,
            })
            return func
        return decorator

    mcp.resource = resource_decorator
    return captured


SAMPLE_SOURCES: dict[str, DocSource] = {
    "atlas-sft": DocSource(
        id="atlas-sft",
        name="ATLAS Software",
        search_index_url=(
            "https://atlas-software.docs.cern.ch/search/search_index.json"
        ),
        repo_url=(
            "https://gitlab.cern.ch/atlas/software-docs/atlas-software-docs"
        ),
        docs_site_url="https://atlas-software.docs.cern.ch",
    ),
    "batch": DocSource(
        id="batch",
        name="HTCondor Batch",
        search_index_url=(
            "https://batchdocs.web.cern.ch/search/search_index.json"
        ),
        repo_url="https://gitlab.cern.ch/batch/batchdocs",
        docs_site_url="https://batchdocs.web.cern.ch",
    ),
}


class TestRegister:
    def test_registers_sources_resource(self) -> None:
        mcp = MagicMock()
        captured = _capture_resource(mcp)
        register(mcp, SAMPLE_SOURCES)

        assert len(captured) == 1
        entry = captured[0]
        assert entry["uri"] == "docs://sources"
        assert entry["mime_type"] == "text/markdown"

        body = entry["func"]()
        # Lists every registered source by id and name.
        assert "atlas-sft" in body
        assert "ATLAS Software" in body
        assert "batch" in body
        assert "HTCondor Batch" in body
        # Includes URLs (Resource Reference pattern - point, don't embed).
        assert "https://atlas-software.docs.cern.ch" in body
        assert "https://batchdocs.web.cern.ch" in body

    def test_handles_empty_registry(self) -> None:
        mcp = MagicMock()
        captured = _capture_resource(mcp)
        register(mcp, {})

        assert len(captured) == 1
        body = captured[0]["func"]()
        assert "no sources registered" in body
