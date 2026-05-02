# cern-mkcern-mkdocs-mcp — Contributor Guide

## Architecture

```
LLM <--MCP/stdio|HTTP--> cern-mkcern-mkdocs-mcp serve
                              |
                              +-- /search/search_index.json   (cached, BM25)
                              |     atlas-software.docs.cern.ch
                              |
                              +-- GitLab Files Raw API        (live)
                                    gitlab.cern.ch/api/v4
```

The server has two backends:

- **MkDocs search payload** — `https://atlas-software.docs.cern.ch/search/search_index.json`,
  refreshed at most every 24 h. We build an in-memory BM25 ranker over
  the per-page `title + text` blobs in that payload (one ranker per
  process, lazy-loaded). We deliberately do not reuse the Lunr index
  embedded in the JSON.
- **GitLab Files Raw API** — `https://gitlab.cern.ch/api/v4/projects/202647/repository/files/<path>/raw?ref=main`.
  Public project, no token.

## Project layout

```
src/cern_mkdocs_mcp/
├── __init__.py           # Package version
├── cli.py                # argparse CLI: `cern-mkcern-mkdocs-mcp serve`
├── server.py             # FastMCP setup, lifespan, defaults
├── nomenclature.py       # ATLAS_SOFTWARE_DOCS_GUIDE (resource + instructions)
├── resources.py          # MCP resource registration
└── tools/
    ├── __init__.py
    ├── _helpers.py       # format_error (Recovery Guide pattern)
    ├── _index.py         # DocsIndex: BM25 over the published MkDocs payload
    ├── search.py         # search_atlas_software_docs
    └── fetch.py          # fetch_atlas_software_doc (markdown / outline / sections)
```

## Key conventions

### Tool registration pattern

Each tool module exports `register(mcp: FastMCP) -> None`:

```python
def register(mcp: FastMCP) -> None:
    @mcp.tool()
    async def my_tool(arg: str, *, ctx: Context[Any, Any]) -> str:
        ctxd = ctx.request_context.lifespan_context
        http = ctxd["http"]
        ...
        return json.dumps(result, default=str)
```

Tools always return a JSON string (token-efficient, easy to log).

### arcade.dev patterns applied

- **Recovery Guide** — use `format_error(exc, recovery=[...])` instead
  of raising. Include concrete follow-up tool calls (most often,
  "call `search_atlas_software_docs` first").
- **Natural Identifier** — `fetch_atlas_software_doc` accepts URL,
  relative path, or `.md` path; `_candidate_source_paths` does the
  resolution.
- **Token-Efficient Response** — `search_atlas_software_docs` returns
  title / URL / snippet only. The agent decides which hit is worth a
  body fetch.
- **Progressive Detail / Operation Mode** — `fetch_atlas_software_doc`
  supports `outline` and `sections:<heading>` projections so the agent
  can scout a long page without paying for the full body.
- **Context Boundary** — the tool descriptions and the
  `atlas-software-docs://guide` resource explicitly say what is *not*
  in scope, to avoid colliding with `cernopendata` / `atlasopenmagic`.

### Error handling

Tools never raise — they return error strings:

```python
try:
    ...
except Exception as exc:  # noqa: BLE001
    return format_error(exc, recovery=[
        "next tool to try",
        "or link to a resource the LLM can read",
    ])
```

### Lifespan context

`server.py`'s lifespan opens a shared `httpx.AsyncClient` and creates a
single `DocsIndex` per process:

```python
ctx.request_context.lifespan_context["http"]         # httpx.AsyncClient
ctx.request_context.lifespan_context["index"]        # DocsIndex (lazy)
ctx.request_context.lifespan_context["docs_base"]    # MkDocs site URL
ctx.request_context.lifespan_context["gitlab_api"]   # GitLab API base
ctx.request_context.lifespan_context["project_id"]   # GitLab project id
```

`DocsIndex.ensure_fresh(http)` is the entry point for the search
backend — call it before searching. It is idempotent and TTL-cached
(24 h), so calling it on every search is cheap.

## Adding a new tool

1. Create `src/cern_mkdocs_mcp/tools/my_module.py` with a
   `register(mcp)` function.
2. Import and register in `server.py`:
   ```python
   from cern_mkdocs_mcp.tools import my_module
   for _module in [search, fetch, my_module]:
   ```
3. Add tests in `tests/test_tools_my_module.py`.
4. Run `pixi run check`.

Resist adding tools speculatively — the design intentionally exposes
only two. If you find yourself wanting a third, prefer extending an
existing tool with a new `mode` (Operation Mode pattern) over a new
tool name.

## Build & test

```bash
pixi run test          # Quick tests (mocked, no network)
pixi run test-cov      # With coverage
pixi run lint          # Pre-commit + pylint
pixi run check         # Lint + test
pixi run check-all     # Lint + all tests with coverage
```

## Tests are offline by design

Every test mocks the upstream HTTP. There is no `--runslow` integration
test against the live docs site yet — add one under
`@pytest.mark.slow` if you need it, but the contract is small enough
that the fast tests cover it.

## Index freshness in production

`DocsIndex` refreshes after `_TTL_SECONDS = 24 * 3600`. If the docs site
ships a hot fix, restart the server (or wait up to 24 h). The TTL is in
`tools/_index.py`; bump it down if rapid iteration matters.

## Health check

There is no separate health-check tool by design. The server is
healthy iff `DocsIndex.ensure_fresh()` succeeds; the first
`search_atlas_software_docs` call after start-up is the de-facto
health probe.
