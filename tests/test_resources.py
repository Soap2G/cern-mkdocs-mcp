"""Tests for MCP resource registration."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from atlas_software_docs_mcp.resources import register


class TestRegister:
    def test_registers_guide_resource(self) -> None:
        mcp = MagicMock()
        captured: list[tuple[Any, ...]] = []

        def resource_decorator(
            uri: str,
            *,
            name: str | None = None,
            description: str | None = None,
            mime_type: str | None = None,
        ) -> Any:
            def decorator(func: Any) -> Any:
                captured.append((uri, name, description, mime_type, func))
                return func
            return decorator

        mcp.resource = resource_decorator
        register(mcp)
        assert len(captured) == 1
        uri, name, _description, mime_type, func = captured[0]
        assert uri == "atlas-software-docs://guide"
        assert name and "ATLAS" in name
        assert mime_type == "text/plain"

        body = func()
        assert "ATLAS" in body
        assert "athena" in body.lower()
        # Context Boundary: the guide spells out what is *not* in scope.
        assert "Open Data" in body
