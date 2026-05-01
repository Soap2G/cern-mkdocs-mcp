"""Configuration for documentation sources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["DocSource", "load_sources", "get_default_sources"]


@dataclass(frozen=True)
class DocSource:
    """Configuration for a documentation source."""

    id: str
    """Unique identifier (e.g., 'atlas-sft', 'batch')."""

    name: str
    """Display name (e.g., 'ATLAS Software')."""

    search_index_url: str
    """URL to /search/search_index.json."""

    repo_url: str
    """Base URL of the source repository (GitLab/GitHub)."""

    project_id: str
    """GitLab project ID — either a numeric id (``"202647"``) or the
    raw repo path (``"atlas/software-docs/atlas-software-docs"``).
    Do **not** URL-encode the path here; the fetch tool quotes it
    once before insertion into the API URL."""

    docs_site_url: str
    """Base URL of the rendered documentation site."""

    @property
    def gitlab_api_url(self) -> str:
        """GitLab API URL for raw file access."""
        return "https://gitlab.cern.ch/api/v4"


def get_default_sources() -> dict[str, DocSource]:
    """Load default documentation sources shipped inside the package.

    Looks for ``docs_sources.json`` next to this module so the file is
    found whether the package is installed (wheel/site-packages) or
    used in editable mode.

    Returns:
        Dict mapping source ID to DocSource.
    """
    config_path = Path(__file__).parent / "docs_sources.json"
    return load_sources(config_path)


def load_sources(config_path: str | Path) -> dict[str, DocSource]:
    """Load documentation sources from a JSON config file.

    Args:
        config_path: Path to docs_sources.json file.

    Returns:
        Dict mapping source ID to DocSource.

    Raises:
        FileNotFoundError: If config file not found.
        ValueError: If config is malformed.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    sources: dict[str, DocSource] = {}
    for item in data.get("sources", []):
        try:
            source = DocSource(
                id=item["id"],
                name=item["name"],
                search_index_url=item["search_index_url"],
                repo_url=item["repo_url"],
                project_id=item["project_id"],
                docs_site_url=item["docs_site_url"],
            )
            sources[source.id] = source
        except KeyError as e:
            raise ValueError(f"Missing required field in source config: {e}") from e

    return sources


def validate_source_id(source_id: str, sources: dict[str, DocSource]) -> None:
    """Validate that a source ID exists.

    Args:
        source_id: The source ID to validate.
        sources: Dict of available sources.

    Raises:
        ValueError: If source ID not found.
    """
    if source_id not in sources:
        available = ", ".join(f"'{s}'" for s in sorted(sources.keys()))
        raise ValueError(
            f"Unknown documentation source '{source_id}'. "
            f"Available sources: {available}. "
            f"Call search_docs with one of these sources."
        )


def format_sources_guide(sources: dict[str, DocSource]) -> str:
    """Format available sources as a help message.

    Args:
        sources: Dict of available sources.

    Returns:
        Formatted help text.
    """
    lines = ["Available documentation sources:", ""]
    for source in sorted(sources.values(), key=lambda s: s.id):
        lines.append(f"  • {source.id:20} — {source.name}")
    return "\n".join(lines)
