"""Tests for config.py: parse_repo_path, resolve_auth_headers, MissingAuthError."""

from __future__ import annotations

import pytest

from cern_mkdocs_mcp.config import (
    AuthConfig,
    DocSource,
    MissingAuthError,
    parse_repo_path,
    resolve_auth_headers,
)

# ---------------------------------------------------------------------------
# parse_repo_path
# ---------------------------------------------------------------------------


class TestParseRepoPath:
    def test_typical_gitlab_cern(self) -> None:
        path = parse_repo_path(
            "https://gitlab.cern.ch/atlas/software-docs/atlas-software-docs",
        )
        assert path == "atlas/software-docs/atlas-software-docs"

    def test_short_two_segment_path(self) -> None:
        assert parse_repo_path("https://gitlab.cern.ch/batch/batchdocs") == (
            "batch/batchdocs"
        )

    def test_strips_trailing_dot_git(self) -> None:
        assert parse_repo_path(
            "https://gitlab.com/foo/bar.git",
        ) == "foo/bar"

    def test_trailing_slash_stripped(self) -> None:
        assert parse_repo_path(
            "https://gitlab.cern.ch/atlas/docs/",
        ) == "atlas/docs"

    def test_no_host_raises(self) -> None:
        with pytest.raises(ValueError, match="no host"):
            parse_repo_path("not-a-url")

    def test_empty_path_raises(self) -> None:
        with pytest.raises(ValueError, match="no path"):
            parse_repo_path("https://gitlab.cern.ch/")


# ---------------------------------------------------------------------------
# resolve_auth_headers
# ---------------------------------------------------------------------------

_PUBLIC = DocSource(
    id="batch",
    name="HTCondor Batch",
    search_index_url="https://batchdocs.web.cern.ch/search/search_index.json",
    repo_url="https://gitlab.cern.ch/batch/batchdocs",
    docs_site_url="https://batchdocs.web.cern.ch",
    auth=None,
)

_GATED = DocSource(
    id="atlas-computing",
    name="ATLAS Computing",
    search_index_url=(
        "https://atlas-computing.docs.cern.ch/search/search_index.json"
    ),
    repo_url=(
        "https://gitlab.cern.ch/atlas/computing-docs/atlas-computing-docs"
    ),
    docs_site_url="https://atlas-computing.docs.cern.ch",
    auth=AuthConfig(env_var="DOCS_MCP_CERN_SSO_TOKEN"),
)

_GITLAB_PAT = DocSource(
    id="private-gitlab",
    name="Private GitLab",
    search_index_url="https://private.example.com/search/search_index.json",
    repo_url="https://gitlab.example.com/group/repo",
    docs_site_url="https://private.example.com",
    auth=AuthConfig(
        env_var="MY_GITLAB_PAT",
        header="Private-Token",
        prefix="",
    ),
)


class TestResolveAuthHeaders:
    def test_public_source_returns_empty(self) -> None:
        assert resolve_auth_headers(_PUBLIC) == {}

    def test_missing_env_raises(self) -> None:
        # Ensure the var is absent (monkeypatch not needed; if it happens to
        # be set in the environment, skip gracefully).
        import os
        if os.environ.get("DOCS_MCP_CERN_SSO_TOKEN"):
            pytest.skip("env var is set in the test environment")
        with pytest.raises(MissingAuthError) as exc_info:
            resolve_auth_headers(_GATED)
        err = exc_info.value
        assert err.source_id == "atlas-computing"
        assert err.env_var == "DOCS_MCP_CERN_SSO_TOKEN"

    def test_bearer_token_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DOCS_MCP_CERN_SSO_TOKEN", "mytoken")
        headers = resolve_auth_headers(_GATED)
        assert headers == {"Authorization": "Bearer mytoken"}

    def test_private_token_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_GITLAB_PAT", "glpat-xxxx")
        headers = resolve_auth_headers(_GITLAB_PAT)
        assert headers == {"Private-Token": "glpat-xxxx"}

    def test_whitespace_only_token_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DOCS_MCP_CERN_SSO_TOKEN", "   ")
        with pytest.raises(MissingAuthError):
            resolve_auth_headers(_GATED)


# ---------------------------------------------------------------------------
# MissingAuthError
# ---------------------------------------------------------------------------


class TestMissingAuthError:
    def test_attributes(self) -> None:
        err = MissingAuthError("my-source", "MY_ENV_VAR")
        assert err.source_id == "my-source"
        assert err.env_var == "MY_ENV_VAR"
        assert "MY_ENV_VAR" in str(err)
        assert "my-source" in str(err)

    def test_is_exception(self) -> None:
        with pytest.raises(MissingAuthError):
            raise MissingAuthError("x", "Y")
