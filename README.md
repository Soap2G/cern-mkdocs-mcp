# atlas-software-docs-mcp

MCP Server for the [ATLAS offline software documentation](https://atlas-software.docs.cern.ch).

This server exposes two tools an LLM agent can use to discover and read
the ATLAS software docs (Athena, the developer guide, the trigger
primer, the analysis tutorial, shifts/infra) without crawling.

> **Read-only by design.** No auth, no write tools — the docs source
> repo at [`atlas/software-docs/atlas-software-docs`](https://gitlab.cern.ch/atlas/software-docs/atlas-software-docs)
> is public.

## Architecture

```
LLM <--MCP/stdio|HTTP--> atlas-software-docs-mcp serve
                              |
                              +-- /search/search_index.json   (cached, BM25)
                              |     https://atlas-software.docs.cern.ch
                              |
                              +-- GitLab Files Raw API        (live)
                                    https://gitlab.cern.ch/api/v4/...
```

The MkDocs site already publishes a full search payload at
`/search/search_index.json`. The server downloads it once per 24 h, builds
an in-memory BM25 ranker, and serves search hits from it. Markdown bodies
are pulled live from GitLab on demand.

## Installation

```bash
pip install atlas-software-docs-mcp
```

Or with pixi:

```bash
pixi install
```

## Usage

### As an MCP server (stdio)

```bash
atlas-software-docs-mcp serve
```

### As a remote MCP (Streamable HTTP)

```bash
atlas-software-docs-mcp serve --transport streamable-http --port 8000
```

This is the deployment shape used by the sibling MCPs at
`*.app.cern.ch/mcp`.

### Claude Desktop / opencode (stdio)

```json
{
  "mcpServers": {
    "atlas-software-docs": {
      "command": "atlas-software-docs-mcp",
      "args": ["serve"]
    }
  }
}
```

### opencode-style remote MCP

In `opencode.json`:

```json
"mcp": {
  "atlas-software-docs": {
    "type": "remote",
    "url": "https://atlas-software-docs-mcp.app.cern.ch/mcp",
    "oauth": false
  }
}
```

## Available tools

| Tool | Description |
|------|-------------|
| `search_atlas_software_docs` | BM25 search over the docs (title + URL + snippet only) |
| `fetch_atlas_software_doc` | Fetch one page's Markdown source from GitLab; supports `mode="markdown" \| "outline" \| "sections:<heading>"` |

## Available resources

| URI | Description |
|-----|-------------|
| `atlas-software-docs://guide` | Quick reference: scope, tools, sections, freshness, NOT-in-scope topics |

## Design principles ([arcade.dev](https://www.arcade.dev/patterns) patterns)

The two tools are deliberately small and aligned with arcade.dev
patterns:

- **Query Tool** — both tools are read-only.
- **Tool Description** — descriptions are written for LLM comprehension
  and explicitly disclaim ATLAS Open Data (Context Boundary), so the
  router does not collide with the sibling `cernopendata` /
  `atlasopenmagic` MCPs.
- **Smart Defaults** — `limit=10`, `mode="markdown"`. Most calls pass
  zero optional args.
- **Constrained Input** — `section` is validated against the closed set
  of MkDocs top-level sections; unknown values return a Recovery Guide
  listing the valid ones.
- **Natural Identifier** — `fetch_atlas_software_doc` accepts a
  rendered URL, a relative path, or a direct `.md` path, and resolves
  each shape internally.
- **Token-Efficient Response** — search returns title / URL / snippet
  only (no body); body fetch is a separate call.
- **Progressive Detail / Operation Mode** — fetch supports
  `outline` (headings only) and `sections:<heading>` (one section)
  before the agent commits to the full body.
- **Resource Reference** — every search hit carries the public docs URL
  so it can be cited / re-fetched without paying the search index cost
  again.
- **Recovery Guide** — every error returns a structured string listing
  concrete next-tool calls (e.g. "call `search_atlas_software_docs` to
  find the correct URL first").
- **Idempotent / cacheable** — the search index is cached for 24 h with
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
| `atlas-software-docs-mcp` (this) | ATLAS *internal/offline* software docs (Athena, dev guide, trigger, analysis tutorial) |
| [`cernopendata-mcp`](../cernopendata-mcp) | CERN Open Data portal records, files, glossary |
| [`atlasopenmagic-mcp`](../atlasopenmagic-mcp) | ATLAS metadata catalogue (AMI), dataset / run-list lookups |

The three are designed to be loaded together in
[`open-data-assistant-config`](../open-data-assistant-config); each tool
description spells out its scope to keep the router's confusability low.

## License

[MIT](LICENSE)
