"""Reference text for the ATLAS software docs corpus.

Embedded as the FastMCP ``instructions`` and exposed as the
``atlas-software-docs://guide`` resource.
"""

from __future__ import annotations

ATLAS_SOFTWARE_DOCS_GUIDE = """\
# ATLAS Software Documentation - Quick Reference

Source site: https://atlas-software.docs.cern.ch
Source repo: https://gitlab.cern.ch/atlas/software-docs/atlas-software-docs (public)
Backend: Material for MkDocs

## Scope

This MCP covers the ATLAS *offline / internal* software stack:

- **Athena** - core software framework (configuration, containers,
  performance tools, GPU support).
- **Developers** - Git workflow, IDE integration, CMake builds, coding
  guidelines, tutorials.
- **Trigger** - primer, developer guide, menu construction, analysis tools.
- **Analysis** - the ATLAS analysis software tutorial: setup, physics
  objects, grid computing, statistics.
- **Shifts and Infrastructure** - code review, release coordination,
  platform information.

## NOT in scope (use a sibling MCP)

- ATLAS Open Data and the public open-data portal -> use ``cernopendata``.
- ATLAS metadata catalogue, AMI dataset lookups, run lists -> use
  ``atlasopenmagic``.
- Internal Computing TWiki, indico pages, mailing lists -> out of scope.

## Tools

- ``search_atlas_software_docs(query, section=?, limit=?)`` - BM25 search
  over the published MkDocs search payload. Returns titles, URLs,
  snippets only (no body) for token-efficient discovery.
- ``fetch_atlas_software_doc(url_or_path, mode=?)`` - fetch the upstream
  Markdown source from GitLab. ``mode`` is one of:
    - ``"markdown"`` (default) - full body
    - ``"outline"`` - H1-H3 headings only
    - ``"sections:<heading>"`` - just the matching section

## Typical flow

1. ``search_atlas_software_docs("running athena from cmake")`` ->
   list of hits with URLs.
2. ``fetch_atlas_software_doc(<url>, mode="outline")`` -> headings.
3. ``fetch_atlas_software_doc(<url>, mode="sections:Build")`` -> just
   that section's Markdown.

## Sections (top level)

- ``athena``
- ``developers``
- ``trigger``
- ``analysis``
- ``shifts-and-infrastructure``

## Freshness

The search index is refreshed at most every 24 hours from the published
MkDocs payload at ``/search/search_index.json``. Source markdown is
fetched live from GitLab on each call (HTTP cache friendly).
"""
