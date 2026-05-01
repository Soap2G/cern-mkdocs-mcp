"""Command-line interface for atlas-software-docs-mcp."""

from __future__ import annotations

import argparse

from atlas_software_docs_mcp.server import (
    DEFAULT_DOCS_BASE,
    DEFAULT_GITLAB_API,
    DEFAULT_GITLAB_PROJECT_ID,
    serve,
)


def main() -> None:
    """Entry point for the ``atlas-software-docs-mcp`` command."""
    parser = argparse.ArgumentParser(
        prog="atlas-software-docs-mcp",
        description="MCP Server for the ATLAS offline software documentation",
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
        "--docs-base",
        default=DEFAULT_DOCS_BASE,
        help=(
            "ATLAS software docs site base URL "
            f"(default: {DEFAULT_DOCS_BASE}). Override to point at a "
            "staging build of the MkDocs site."
        ),
    )
    serve_parser.add_argument(
        "--gitlab-api",
        default=DEFAULT_GITLAB_API,
        help=f"GitLab API base URL (default: {DEFAULT_GITLAB_API})",
    )
    serve_parser.add_argument(
        "--project-id",
        default=DEFAULT_GITLAB_PROJECT_ID,
        help=(
            "GitLab project id (or URL-encoded namespace/path) of the "
            f"docs source repo (default: {DEFAULT_GITLAB_PROJECT_ID})."
        ),
    )

    args = parser.parse_args()

    if args.command == "serve":
        serve(
            transport=args.transport,
            host=args.host,
            port=args.port,
            docs_base=args.docs_base,
            gitlab_api=args.gitlab_api,
            project_id=args.project_id,
        )
    else:
        parser.print_help()
