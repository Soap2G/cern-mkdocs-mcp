"""Command-line interface for docs-mcp."""

from __future__ import annotations

import argparse
from pathlib import Path

from atlas_software_docs_mcp.server import serve


def main() -> None:
    """Entry point for the ``docs-mcp`` command."""
    parser = argparse.ArgumentParser(
        prog="docs-mcp",
        description=(
            "MCP Server for searching multiple MkDocs-based documentation "
            "sites via a unified interface."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    serve_parser = subparsers.add_parser(
        "serve",
        help="Start the MCP server",
    )
    serve_parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio). Use 'streamable-http' "
             "for OpenWebUI / opencode-remote-MCP / Claude Desktop remote.",
    )
    serve_parser.add_argument(
        "--host",
        default="0.0.0.0",  # noqa: S104
        help="Bind address for HTTP transport (default: 0.0.0.0)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)",
    )
    serve_parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Path to a JSON config defining documentation sources. "
            "When omitted, the package-bundled docs_sources.json is used."
        ),
    )

    args = parser.parse_args()

    if args.command == "serve":
        serve(
            transport=args.transport,
            host=args.host,
            port=args.port,
            config_path=args.config,
        )
    else:
        parser.print_help()
