"""Configuration for documentation sources.

This module owns the source registry: how each documentation site is
addressed (search index URL, repo URL, rendered site URL) and how it is
authenticated (a single optional :class:`AuthConfig` per source).

Auth follows the arcade.dev *Secret Injection* pattern: tokens never
travel through the LLM. They are read at request time from environment
variables named in :class:`AuthConfig`, attached to the outgoing HTTP
header, and discarded.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

__all__ = [
    "AuthConfig",
    "DocSource",
    "MissingAuthError",
    "format_sources_guide",
    "get_default_sources",
    "load_sources",
    "parse_repo_path",
    "public_source_ids",
    "resolve_auth_headers",
    "validate_source_id",
]


@dataclass(frozen=True)
class AuthConfig:
    """How to authenticate against an auth-gated source.

    The token is read at request time from ``env_var`` and assigned to
    one HTTP header. Public sources do not need this block.

    Examples:
        ``AuthConfig(env_var="DOCS_MCP_CERN_SSO_TOKEN")``
            -> ``Authorization: Bearer <token>`` (default).
        ``AuthConfig(env_var="GITLAB_PAT", header="Private-Token", prefix="")``
            -> ``Private-Token: <token>``.
    """

    env_var: str
    """Name of the environment variable holding the credential."""

    header: str = "Authorization"
    """HTTP header to set."""

    prefix: str = "Bearer "
    """Prepended to the env value before assignment to the header.
    For Bearer (OIDC, OAuth) tokens, leave the default. For GitLab
    PATs, set ``header="Private-Token"`` and ``prefix=""``."""


@dataclass(frozen=True)
class DocSource:
    """Configuration for a documentation source.

    The GitLab project path is derived from :attr:`repo_url` on demand
    (see :attr:`gitlab_project_path`), so callers do not need to know
    or supply numeric GitLab project ids.
    """

    id: str
    """Unique identifier (e.g. ``'atlas-sft'``, ``'batch'``)."""

    name: str
    """Display name."""

    search_index_url: str
    """URL of the published MkDocs ``search_index.json``."""

    repo_url: str
    """Public URL of the source repository (e.g. a GitLab project URL)."""

    docs_site_url: str
    """Base URL of the rendered documentation site."""

    auth: AuthConfig | None = None
    """Auth config for protected sources, or ``None`` for public ones."""

    @property
    def gitlab_project_path(self) -> str:
        """Path component of the GitLab repo URL (raw, not URL-encoded)."""
        return parse_repo_path(self.repo_url)


class MissingAuthError(Exception):
    """Raised when an auth-gated source is queried without credentials.

    Tools catch this and translate it into a Recovery Guide for the LLM
    rather than letting the exception propagate. The :attr:`env_var`
    attribute lets the recovery message tell the user *exactly* which
    environment variable to set.
    """

    def __init__(self, source_id: str, env_var: str) -> None:
        self.source_id = source_id
        self.env_var = env_var
        super().__init__(
            f"Source {source_id!r} is auth-gated: set ${env_var} to a "
            "valid token before querying it.",
        )


def parse_repo_path(repo_url: str) -> str:
    """Extract the GitLab project path from a repo URL.

    For ``https://gitlab.cern.ch/atlas/software-docs/atlas-software-docs``
    returns ``"atlas/software-docs/atlas-software-docs"`` (raw, not
    URL-encoded). The fetch tool URL-encodes it via :func:`urllib.parse.quote`
    once before insertion into the API URL. Strips a trailing ``.git``
    if present.

    Currently assumes the repo follows GitLab's standard
    ``/<group>/<...>/<repo>`` URL shape (``gitlab.cern.ch`` and
    ``gitlab.com`` both qualify). Non-GitLab repos (e.g. github.com)
    would need per-source handling at the fetch tool.
    """
    parsed = urlparse(repo_url)
    if not parsed.netloc:
        msg = f"repo_url has no host: {repo_url!r}"
        raise ValueError(msg)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    if not path:
        msg = f"repo_url has no path: {repo_url!r}"
        raise ValueError(msg)
    return path


def resolve_auth_headers(source: DocSource) -> dict[str, str]:
    """Return HTTP headers needed to fetch from ``source``.

    For public sources returns ``{}``. For auth-gated sources reads the
    configured environment variable and returns a one-header dict.

    Raises:
        MissingAuthError: if the source is auth-gated and the env var
            is unset or empty.
    """
    if source.auth is None:
        return {}
    token = os.environ.get(source.auth.env_var, "").strip()
    if not token:
        raise MissingAuthError(source.id, source.auth.env_var)
    return {source.auth.header: f"{source.auth.prefix}{token}"}


def public_source_ids(sources: dict[str, DocSource]) -> list[str]:
    """Return the IDs of sources that need no auth, sorted alphabetically."""
    return sorted(s.id for s in sources.values() if s.auth is None)


def get_default_sources() -> dict[str, DocSource]:
    """Load default documentation sources shipped inside the package."""
    config_path = Path(__file__).parent / "docs_sources.json"
    return load_sources(config_path)


def load_sources(config_path: str | Path) -> dict[str, DocSource]:
    """Load documentation sources from a JSON config file.

    Schema (one entry per source)::

        {
          "id": "...",
          "name": "...",
          "search_index_url": "...",
          "repo_url": "...",
          "docs_site_url": "...",
          "auth": {
            "env_var": "...",
            "header": "...",     // optional, default "Authorization"
            "prefix": "..."      // optional, default "Bearer "
          }
        }

    The ``auth`` block is optional; omit it for public sources.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        msg = f"Config file not found: {config_path}"
        raise FileNotFoundError(msg)

    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)

    sources: dict[str, DocSource] = {}
    for item in data.get("sources", []):
        try:
            auth: AuthConfig | None = None
            auth_data = item.get("auth")
            if auth_data:
                auth = AuthConfig(
                    env_var=auth_data["env_var"],
                    header=auth_data.get("header", "Authorization"),
                    prefix=auth_data.get("prefix", "Bearer "),
                )
            source = DocSource(
                id=item["id"],
                name=item["name"],
                search_index_url=item["search_index_url"],
                repo_url=item["repo_url"],
                docs_site_url=item["docs_site_url"],
                auth=auth,
            )
            sources[source.id] = source
        except KeyError as exc:
            msg = f"Missing required field in source config: {exc}"
            raise ValueError(msg) from exc

    return sources


def validate_source_id(source_id: str, sources: dict[str, DocSource]) -> None:
    """Raise ``ValueError`` if ``source_id`` is not in the registry."""
    if source_id not in sources:
        available = ", ".join(f"'{s}'" for s in sorted(sources.keys()))
        msg = (
            f"Unknown documentation source '{source_id}'. "
            f"Available sources: {available}."
        )
        raise ValueError(msg)


def format_sources_guide(sources: dict[str, DocSource]) -> str:
    """Render the source registry as a human-readable bullet list.

    Auth-gated sources are tagged with the env var the caller must set.
    Used in Recovery Guide messages and the ``docs://sources`` resource.
    """
    lines = ["Available documentation sources:", ""]
    for source in sorted(sources.values(), key=lambda s: s.id):
        marker = ""
        if source.auth is not None:
            marker = f"  [auth: ${source.auth.env_var}]"
        lines.append(f"  - {source.id:20} - {source.name}{marker}")
    return "\n".join(lines)
