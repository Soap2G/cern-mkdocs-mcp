# docs-mcp

MCP Server for searching multiple MkDocs-based documentation sites via a unified interface.

This server exposes two tools an LLM agent can use to discover and read
documentation from multiple CERN sites (ATLAS software docs, computing docs,
batch, cloud, ML, SWAN, and more) without crawling.

> **Read-only by design.** No auth, no write tools — all documentation
> sources are public.

## Architecture

```
LLM <--MCP/stdio|HTTP--> docs-mcp serve
                            |
                            +-- Multiple doc sources:
                            |   +-- search_index.json (cached, BM25)
                            |   +-- https://atlas-software.docs.cern.ch
                            |   +-- https://atlas-computing.docs.cern.ch
                            |   +-- https://atlas-databases.docs.cern.ch
                            |   +-- https://batchdocs.web.cern.ch
                            |   +-- https://clouddocs.web.cern.ch
                            |   +-- https://ml.docs.cern.ch
                            |   +-- https://swan.docs.cern.ch
                            |
                            +-- GitLab/GitHub Raw API (live)
                                  https://gitlab.cern.ch/api/v4/...
```

Each MkDocs site publishes a search payload at `/search/search_index.json`.
The server downloads each index once per 24 h, builds in-memory BM25 rankers,
and serves search hits from them. Markdown bodies are pulled live from VCS
on demand.

## Installation

```bash
pip install docs-mcp
```

Or with pixi:

```bash
pixi install
```

## Usage

### As an MCP server (stdio)

```bash
docs-mcp serve
```

Or with a custom config file:

```bash
docs-mcp serve --config /path/to/docs-sources.json
```

### As a remote MCP (Streamable HTTP)

```bash
docs-mcp serve --transport streamable-http --port 8000
```

This is the deployment shape used by MCP servers at `*.app.cern.ch/mcp`.

### Claude Desktop / opencode (stdio)

```json
{
  "mcpServers": {
    "docs": {
      "command": "docs-mcp",
      "args": ["serve"]
    }
  }
}
```

### opencode-style remote MCP

In `opencode.json`:

```json
"mcp": {
  "docs": {
    "type": "remote",
    "url": "https://docs-mcp.app.cern.ch/mcp",
    "oauth": false
  }
}
```

## Available tools

| Tool | Description |
|------|-------------|
| `search_docs` | BM25 search across a chosen documentation source (title + URL + snippet only); `source` param chooses which docs site to search |
| `fetch_doc` | Fetch one page's Markdown/outline from the source repository; supports `mode="markdown" \| "outline" \| "sections:<heading>"` |

### Supported doc sources

| Source ID | Documentation |
|-----------|---------------|
| `atlas-sft` | [ATLAS software/Athena](https://atlas-software.docs.cern.ch) |
| `atlas-computing` | [ATLAS computing guide](https://atlas-computing.docs.cern.ch) |
| `atlas-databases` | [ATLAS databases](https://atlas-databases.docs.cern.ch) |
| `batch` | [HTCondor Batch](https://batchdocs.web.cern.ch) |
| `cloud` | [CERN Cloud](https://clouddocs.web.cern.ch) |
| `ml` | [ML@CERN](https://ml.docs.cern.ch) |
| `swan` | [SWAN (Jupyter)](https://swan.docs.cern.ch) |

## Available resources

| URI | Description |
|-----|-------------|
| `docs://sources` | Lists all registered documentation sources and metadata (URLs, VCS paths, freshness) |

## Design principles ([arcade.dev](https://www.arcade.dev/patterns) patterns)

The two tools are deliberately small and aligned with arcade.dev patterns:

- **Query Tool** — both tools are read-only.
- **Tool Description** — descriptions are written for LLM comprehension
  with explicit scope boundaries to avoid router confusion.
- **Multi-source Router** — `source` parameter routes requests to the
  correct documentation index; unknown values return a Recovery Guide
  listing valid sources.
- **Smart Defaults** — `limit=10`, `mode="markdown"`, `source="atlas-sft"`.
  Most calls pass zero optional args.
- **Constrained Input** — `source` is validated against the closed set
  of registered documentation sites.
- **Natural Identifier** — `fetch_doc` accepts a rendered URL, a relative
  path, or a direct `.md` path, and resolves each shape internally.
- **Token-Efficient Response** — search returns title / URL / snippet
  only (no body); body fetch is a separate call.
- **Progressive Detail / Operation Mode** — fetch supports
  `outline` (headings only) and `sections:<heading>` (one section)
  before the agent commits to the full body.
- **Resource Reference** — every search hit carries the public docs URL
  so it can be cited / re-fetched without paying the search index cost
  again.
- **Recovery Guide** — every error returns a structured string listing
  concrete next-tool calls (e.g. "call `search_docs` with `source="batch"`
  to find the correct URL first").
- **Idempotent / cacheable** — search indexes are cached for 24 h with
  staleness checks; Markdown fetches piggyback on HTTP caching.
- **Tool Versioning** — the package version (`__init__.py:__version__`)
  is the durable handle; pin it on the deployment side.

## Development

```bash
pixi run test          # Quick tests (mocked, no network)
pixi run test-cov      # With coverage
pixi run lint          # Pre-commit + pylint
pixi run check         # Lint + test
pixi run check-all     # Lint + all tests with coverage
```

Tests are fully offline — the BM25 index is fed a small fixture corpus,
and the GitLab raw fetcher is mocked. No CERN network access required.

## Relationship to sibling MCPs

| MCP | Scope |
|-----|-------|
| `docs-mcp` (this) | Multi-source: ATLAS software/computing/databases, Batch, Cloud, ML@CERN, SWAN |
| [`cernopendata-mcp`](../cernopendata-mcp) | CERN Open Data portal records, files, glossary |
| [`atlasopenmagic-mcp`](../atlasopenmagic-mcp) | ATLAS metadata catalogue (AMI), dataset / run-list lookups |

The three are designed to be loaded together in
[`open-data-assistant-config`](../open-data-assistant-config); each tool
description spells out its scope to keep the router's confusability low.

## License

[MIT](LICENSE)
