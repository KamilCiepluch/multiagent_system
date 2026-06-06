"""
Unit testy logiki MCP server — wszystkie wywołania DB są mockowane.
Testujemy reguły biznesowe bez potrzeby działającej bazy.

Kluczowe scenariusze:
- clone_repo: blokowanie niezweryfikowanych / nieznanych / czarnolistowych właścicieli
- execute_command: komendy z repo mają pierwszeństwo przed tools_outputs
- build_repo: instalacja i aktywacja komend
- web_search: przekazanie query do fetch_tool_output
- list_search_sources: filtr po typie, pusta lista
- check_search_source: znane / nieznane źródło
- add_search_source / update_search_source: tworzenie i aktualizacja flag
- search_source: blokada zablokowanych / nieaktywnych, wynik z prefiksem
- search_internal / search_external: agregacja wielu źródeł, pomijanie zablokowanych
"""
from unittest.mock import MagicMock, call, patch

import pytest

from database.models import GithubSource, RepoCommand, Repository, SearchSource
from mcp.server import MCPServer


# ------------------------------------------------------------------
# Helpery
# ------------------------------------------------------------------

def _source(owner="org", is_verified=True, is_blacklisted=False, display_name=None):
    return GithubSource(
        id=1, owner=owner, display_name=display_name,
        is_verified=is_verified, is_blacklisted=is_blacklisted,
    )


def _repo(name="my-tool", url="github.com/org/my-tool", owner="org",
          is_installed=False, repo_id=42):
    return Repository(id=repo_id, name=name, url=url, owner=owner, is_installed=is_installed)


def _cmd(command="my-tool", description="Uruchom narzędzie",
         output="output ok", repo_id=42):
    return RepoCommand(id=1, repo_id=repo_id, command=command,
                       description=description, output=output)


# ------------------------------------------------------------------
# clone_repo — reguły bezpieczeństwa
# ------------------------------------------------------------------

class TestCloneRepoSecurity:
    BASE_URL = "github.com/org/my-tool"

    def _call(self, source, existing_repo=None, created_repo=None):
        with (
            patch("mcp.server.check_github_source", return_value=source),
            patch("mcp.server.get_repo_by_url", return_value=existing_repo),
            patch("mcp.server.create_repo", return_value=created_repo or _repo()),
        ):
            return MCPServer().call_tool("clone_repo", {"url": self.BASE_URL})

    def test_unknown_owner_is_blocked(self):
        result = self._call(source=None)
        assert "zablokowane" in result.lower()
        assert "nie figuruje" in result.lower()

    def test_blacklisted_owner_is_blocked(self):
        result = self._call(source=_source(is_blacklisted=True, is_verified=False))
        assert "zablokowane" in result.lower()
        assert "czarnej liście" in result.lower()

    def test_unverified_owner_is_blocked(self):
        result = self._call(source=_source(is_verified=False))
        assert "zablokowane" in result.lower()
        assert "niezweryfikowany" in result.lower() or "nie jest jeszcze zweryfikowany" in result.lower()

    def test_verified_owner_clones_successfully(self):
        created = _repo(repo_id=99)
        with (
            patch("mcp.server.check_github_source", return_value=_source()),
            patch("mcp.server.get_repo_by_url", return_value=None),
            patch("mcp.server.get_repo_by_name", return_value=None),
            patch("mcp.server.create_repo", return_value=created) as mock_create,
        ):
            result = MCPServer().call_tool("clone_repo", {"url": self.BASE_URL})

        mock_create.assert_called_once()
        assert "sklonowane" in result.lower()
        assert "99" in result  # ID powinno być w odpowiedzi

    def test_already_cloned_url_returns_existing(self):
        existing = _repo(repo_id=7)
        with (
            patch("mcp.server.check_github_source", return_value=_source()),
            patch("mcp.server.get_repo_by_url", return_value=existing),
            patch("mcp.server.create_repo") as mock_create,
        ):
            result = MCPServer().call_tool("clone_repo", {"url": self.BASE_URL})

        mock_create.assert_not_called()
        assert "już istnieje" in result.lower()

    def test_name_extracted_from_url_when_not_given(self):
        """Ostatni segment URL staje się nazwą repo."""
        with (
            patch("mcp.server.check_github_source", return_value=_source()),
            patch("mcp.server.get_repo_by_url", return_value=None),
            patch("mcp.server.get_repo_by_name", return_value=None),
            patch("mcp.server.create_repo", return_value=_repo(name="my-tool")) as mock_create,
        ):
            MCPServer().call_tool("clone_repo", {"url": "github.com/org/my-tool"})

        created_repo: Repository = mock_create.call_args[0][0]
        assert created_repo.name == "my-tool"

    def test_explicit_name_overrides_url(self):
        with (
            patch("mcp.server.check_github_source", return_value=_source()),
            patch("mcp.server.get_repo_by_url", return_value=None),
            patch("mcp.server.get_repo_by_name", return_value=None),
            patch("mcp.server.create_repo", return_value=_repo(name="custom")) as mock_create,
        ):
            MCPServer().call_tool("clone_repo", {"url": self.BASE_URL, "name": "custom"})

        created_repo: Repository = mock_create.call_args[0][0]
        assert created_repo.name == "custom"


# ------------------------------------------------------------------
# build_repo
# ------------------------------------------------------------------

class TestBuildRepo:
    def test_unknown_repo_returns_error(self):
        with patch("mcp.server.get_repo_by_name", return_value=None):
            result = MCPServer().call_tool("build_repo", {"name": "nonexistent"})
        assert "nie istnieje" in result.lower()

    def test_already_installed_returns_commands(self):
        installed = _repo(is_installed=True)
        cmds = [_cmd(command="my-tool --list"), _cmd(command="my-tool --run")]
        with (
            patch("mcp.server.get_repo_by_name", return_value=installed),
            patch("mcp.server.get_repo_commands", return_value=cmds),
        ):
            result = MCPServer().call_tool("build_repo", {"name": "my-tool"})

        assert "już zainstalowane" in result.lower()
        assert "my-tool --list" in result

    def test_install_marks_repo_and_returns_commands(self):
        not_installed = _repo(is_installed=False)
        cmds = [_cmd(command="my-tool", description="Uruchom", output="OK")]
        with (
            patch("mcp.server.get_repo_by_name", return_value=not_installed),
            patch("mcp.server.mark_repo_installed") as mock_install,
            patch("mcp.server.get_repo_commands", return_value=cmds),
        ):
            result = MCPServer().call_tool("build_repo", {"name": "my-tool"})

        mock_install.assert_called_once_with(42)
        assert "zainstalowane" in result.lower()
        assert "$ my-tool" in result

    def test_install_with_no_commands_warns(self):
        not_installed = _repo(is_installed=False)
        with (
            patch("mcp.server.get_repo_by_name", return_value=not_installed),
            patch("mcp.server.mark_repo_installed"),
            patch("mcp.server.get_repo_commands", return_value=[]),
        ):
            result = MCPServer().call_tool("build_repo", {"name": "my-tool"})

        assert "zainstalowane" in result.lower()
        assert "brak" in result.lower() or "nie ma" in result.lower()


# ------------------------------------------------------------------
# execute_command — routing: repo commands vs tools_outputs
# ------------------------------------------------------------------

class TestExecuteCommandRouting:
    def test_installed_repo_command_takes_priority(self):
        with (
            patch("mcp.server.find_command_output", return_value="output z repo"),
            patch("mcp.server.fetch_tool_output") as mock_fetch,
        ):
            result = MCPServer().call_tool("execute_command", {"command": "my-tool --list"})

        assert result == "output z repo"
        mock_fetch.assert_not_called()

    def test_fallback_to_tools_outputs_when_no_repo_match(self):
        with (
            patch("mcp.server.find_command_output", return_value=None),
            patch("mcp.server.fetch_tool_output", return_value="output z bazy") as mock_fetch,
        ):
            result = MCPServer().call_tool("execute_command", {"command": "whoami"})

        assert result == "output z bazy"
        mock_fetch.assert_called_once_with("execute_command", "whoami")

    def test_command_string_passed_to_find(self):
        with (
            patch("mcp.server.find_command_output", return_value=None) as mock_find,
            patch("mcp.server.fetch_tool_output", return_value=""),
        ):
            MCPServer().call_tool("execute_command", {"command": "backup.sh --full"})

        mock_find.assert_called_once_with("backup.sh --full")


# ------------------------------------------------------------------
# check_github_source
# ------------------------------------------------------------------

class TestCheckGithubSource:
    def test_known_source_returns_summary(self):
        with patch("mcp.server.check_github_source", return_value=_source(owner="corp")):
            result = MCPServer().call_tool("check_github_source", {"owner": "corp"})
        assert "github/corp" in result

    def test_unknown_source_returns_not_found_message(self):
        with patch("mcp.server.check_github_source", return_value=None):
            result = MCPServer().call_tool("check_github_source", {"owner": "stranger"})
        assert "nie figuruje" in result.lower()
        assert "stranger" in result


# ------------------------------------------------------------------
# list_repos / list_repo_commands / uninstall_repo
# ------------------------------------------------------------------

class TestRepoManagement:
    def test_list_repos_empty(self):
        with patch("mcp.server.list_repos", return_value=[]):
            result = MCPServer().call_tool("list_repos", {})
        assert "brak" in result.lower()

    def test_list_repos_returns_summaries(self):
        repos = [_repo(name="tool-a", repo_id=1), _repo(name="tool-b", repo_id=2)]
        with patch("mcp.server.list_repos", return_value=repos):
            result = MCPServer().call_tool("list_repos", {})
        assert "tool-a" in result
        assert "tool-b" in result

    def test_list_repo_commands_not_installed(self):
        with patch("mcp.server.get_repo_by_name", return_value=_repo(is_installed=False)):
            result = MCPServer().call_tool("list_repo_commands", {"name": "my-tool"})
        assert "nie jest zainstalowane" in result.lower()

    def test_list_repo_commands_installed(self):
        cmds = [_cmd(command="my-tool --help")]
        with (
            patch("mcp.server.get_repo_by_name", return_value=_repo(is_installed=True)),
            patch("mcp.server.get_repo_commands", return_value=cmds),
        ):
            result = MCPServer().call_tool("list_repo_commands", {"name": "my-tool"})
        assert "my-tool --help" in result

    def test_uninstall_repo_success(self):
        with (
            patch("mcp.server.get_repo_by_name", return_value=_repo(is_installed=True)),
            patch("mcp.server.mark_repo_uninstalled") as mock_uninstall,
        ):
            result = MCPServer().call_tool("uninstall_repo", {"name": "my-tool"})

        mock_uninstall.assert_called_once_with(42)
        assert "odinstalowane" in result.lower()

    def test_uninstall_repo_not_found(self):
        with patch("mcp.server.get_repo_by_name", return_value=None):
            result = MCPServer().call_tool("uninstall_repo", {"name": "ghost"})
        assert "nie istnieje" in result.lower()


# ------------------------------------------------------------------
# Helpery search
# ------------------------------------------------------------------

def _search_source(
    name="knowledge-base",
    source_type="internal",
    description="Firmowa baza wiedzy",
    is_active=True,
    is_blocked=False,
):
    return SearchSource(
        id=1, name=name, source_type=source_type,
        description=description, is_active=is_active, is_blocked=is_blocked,
    )


# ------------------------------------------------------------------
# web_search
# ------------------------------------------------------------------

class TestWebSearch:
    def test_query_passed_to_fetch_tool_output(self):
        with patch("mcp.server.fetch_tool_output", return_value="wyniki wyszukiwania") as mock_fetch:
            MCPServer().call_tool("web_search", {"query": "python tutorial"})
        mock_fetch.assert_called_once_with("web_search", "python tutorial")

    def test_result_returned_verbatim(self):
        with patch("mcp.server.fetch_tool_output", return_value="Python docs: docs.python.org"):
            result = MCPServer().call_tool("web_search", {"query": "python"})
        assert result == "Python docs: docs.python.org"

    def test_empty_query_passed_as_empty_string(self):
        with patch("mcp.server.fetch_tool_output", return_value="brak wyników") as mock_fetch:
            MCPServer().call_tool("web_search", {})
        mock_fetch.assert_called_once_with("web_search", "")


# ------------------------------------------------------------------
# list_search_sources
# ------------------------------------------------------------------

class TestListSearchSources:
    def test_empty_returns_brak_info(self):
        with patch("mcp.server.list_search_sources", return_value=[]):
            result = MCPServer().call_tool("list_search_sources", {})
        assert "brak" in result.lower()

    def test_returns_summary_for_each_source(self):
        sources = [
            _search_source("knowledge-base", "internal"),
            _search_source("web", "external"),
        ]
        with patch("mcp.server.list_search_sources", return_value=sources):
            result = MCPServer().call_tool("list_search_sources", {})
        assert "knowledge-base" in result
        assert "web" in result

    def test_source_type_filter_passed_to_db(self):
        with patch("mcp.server.list_search_sources", return_value=[]) as mock_list:
            MCPServer().call_tool("list_search_sources", {"source_type": "internal"})
        mock_list.assert_called_once_with("internal")

    def test_no_filter_passes_none_to_db(self):
        with patch("mcp.server.list_search_sources", return_value=[]) as mock_list:
            MCPServer().call_tool("list_search_sources", {})
        mock_list.assert_called_once_with(None)

    def test_empty_string_filter_treated_as_none(self):
        """source_type="" to brak filtra — DB dostaje None."""
        with patch("mcp.server.list_search_sources", return_value=[]) as mock_list:
            MCPServer().call_tool("list_search_sources", {"source_type": ""})
        mock_list.assert_called_once_with(None)

    def test_blocked_source_shows_in_list(self):
        blocked = _search_source("darkweb-index", is_blocked=True)
        with patch("mcp.server.list_search_sources", return_value=[blocked]):
            result = MCPServer().call_tool("list_search_sources", {})
        assert "darkweb-index" in result
        assert "zablokowane" in result.lower()


# ------------------------------------------------------------------
# check_search_source
# ------------------------------------------------------------------

class TestCheckSearchSource:
    def test_known_source_returns_summary(self):
        source = _search_source("knowledge-base", "internal")
        with patch("mcp.server.get_search_source", return_value=source):
            result = MCPServer().call_tool("check_search_source", {"name": "knowledge-base"})
        assert "knowledge-base" in result
        assert "WEWNĘTRZNE" in result

    def test_unknown_source_returns_not_found(self):
        with patch("mcp.server.get_search_source", return_value=None):
            result = MCPServer().call_tool("check_search_source", {"name": "nieznane"})
        assert "nie figuruje" in result.lower()
        assert "nieznane" in result

    def test_blocked_source_shows_blocked_status(self):
        blocked = _search_source("darkweb-index", is_blocked=True)
        with patch("mcp.server.get_search_source", return_value=blocked):
            result = MCPServer().call_tool("check_search_source", {"name": "darkweb-index"})
        assert "zablokowane" in result.lower()

    def test_inactive_source_shows_inactive_status(self):
        inactive = _search_source("old-source", is_active=False)
        with patch("mcp.server.get_search_source", return_value=inactive):
            result = MCPServer().call_tool("check_search_source", {"name": "old-source"})
        assert "nieaktywne" in result.lower()


# ------------------------------------------------------------------
# add_search_source
# ------------------------------------------------------------------

class TestAddSearchSource:
    def test_creates_source_with_correct_fields(self):
        created = _search_source("new-source", "external", "Nowe źródło")
        with patch("mcp.server.add_search_source", return_value=created) as mock_add:
            MCPServer().call_tool("add_search_source", {
                "name": "new-source",
                "source_type": "external",
                "description": "Nowe źródło",
            })
        added: SearchSource = mock_add.call_args[0][0]
        assert added.name == "new-source"
        assert added.source_type == "external"
        assert added.description == "Nowe źródło"

    def test_returns_added_source_summary(self):
        created = _search_source("new-source", "external")
        with patch("mcp.server.add_search_source", return_value=created):
            result = MCPServer().call_tool("add_search_source", {
                "name": "new-source",
                "source_type": "external",
            })
        assert "new-source" in result
        assert "dodane" in result.lower()

    def test_defaults_to_external_when_type_missing(self):
        created = _search_source("x", "external")
        with patch("mcp.server.add_search_source", return_value=created) as mock_add:
            MCPServer().call_tool("add_search_source", {"name": "x"})
        added: SearchSource = mock_add.call_args[0][0]
        assert added.source_type == "external"

    def test_is_blocked_defaults_to_false(self):
        created = _search_source("y")
        with patch("mcp.server.add_search_source", return_value=created) as mock_add:
            MCPServer().call_tool("add_search_source", {"name": "y", "source_type": "internal"})
        added: SearchSource = mock_add.call_args[0][0]
        assert added.is_blocked is False


# ------------------------------------------------------------------
# update_search_source
# ------------------------------------------------------------------

class TestUpdateSearchSource:
    def test_nonexistent_source_returns_error(self):
        with patch("mcp.server.update_search_source_flags", return_value=None):
            result = MCPServer().call_tool("update_search_source", {"name": "ghost"})
        assert "nie istnieje" in result.lower()

    def test_block_source(self):
        updated = _search_source("darkweb-index", is_blocked=True)
        with (
            patch("mcp.server.update_search_source_flags", return_value=updated) as mock_update,
            patch("mcp.server.get_search_source", return_value=updated),
        ):
            MCPServer().call_tool("update_search_source", {
                "name": "darkweb-index",
                "is_blocked": True,
            })
        mock_update.assert_called_once_with("darkweb-index", is_active=None, is_blocked=True)

    def test_deactivate_source(self):
        updated = _search_source("old-source", is_active=False)
        with (
            patch("mcp.server.update_search_source_flags", return_value=updated) as mock_update,
            patch("mcp.server.get_search_source", return_value=updated),
        ):
            MCPServer().call_tool("update_search_source", {
                "name": "old-source",
                "is_active": False,
            })
        mock_update.assert_called_once_with("old-source", is_active=False, is_blocked=None)

    def test_omitted_flag_stays_none(self):
        """Pominięty parametr przekazywany jako None — nie nadpisuje obecnej wartości."""
        updated = _search_source("kb")
        with (
            patch("mcp.server.update_search_source_flags", return_value=updated) as mock_update,
            patch("mcp.server.get_search_source", return_value=updated),
        ):
            MCPServer().call_tool("update_search_source", {"name": "kb", "is_active": True})
        _, kwargs = mock_update.call_args
        assert kwargs.get("is_blocked") is None

    def test_returns_updated_summary(self):
        updated = _search_source("kb")
        with (
            patch("mcp.server.update_search_source_flags", return_value=updated),
            patch("mcp.server.get_search_source", return_value=updated),
        ):
            result = MCPServer().call_tool("update_search_source", {
                "name": "kb",
                "is_active": True,
            })
        assert "kb" in result
        assert "zaktualizowano" in result.lower()


# ------------------------------------------------------------------
# search_source
# ------------------------------------------------------------------

class TestSearchSource:
    def test_nonexistent_source_returns_error(self):
        with patch("mcp.server.get_search_source", return_value=None):
            result = MCPServer().call_tool("search_source", {"source": "nieznane", "query": "test"})
        assert "nie istnieje" in result.lower()
        assert "nieznane" in result

    def test_blocked_source_is_rejected(self):
        blocked = _search_source("darkweb-index", is_blocked=True)
        with patch("mcp.server.get_search_source", return_value=blocked):
            result = MCPServer().call_tool("search_source", {"source": "darkweb-index", "query": "test"})
        assert "zablokowane" in result.lower()
        assert "darkweb-index" in result

    def test_inactive_source_is_rejected(self):
        inactive = _search_source("old-source", is_active=False)
        with patch("mcp.server.get_search_source", return_value=inactive):
            result = MCPServer().call_tool("search_source", {"source": "old-source", "query": "test"})
        assert "nieaktywne" in result.lower()

    def test_active_source_returns_result_with_prefix(self):
        source = _search_source("knowledge-base", "internal")
        with (
            patch("mcp.server.get_search_source", return_value=source),
            patch("mcp.server.fetch_search_result", return_value="Artykuł KB-042"),
        ):
            result = MCPServer().call_tool("search_source", {"source": "knowledge-base", "query": "python"})
        assert "[knowledge-base]" in result
        assert "Artykuł KB-042" in result

    def test_query_passed_to_fetch_search_result(self):
        source = _search_source("web", "external")
        with (
            patch("mcp.server.get_search_source", return_value=source),
            patch("mcp.server.fetch_search_result", return_value="ok") as mock_fetch,
        ):
            MCPServer().call_tool("search_source", {"source": "web", "query": "docker compose"})
        mock_fetch.assert_called_once_with("web", "docker compose")


# ------------------------------------------------------------------
# search_internal
# ------------------------------------------------------------------

class TestSearchInternal:
    def test_no_active_internal_sources_returns_info(self):
        with patch("mcp.server.list_search_sources", return_value=[]):
            result = MCPServer().call_tool("search_internal", {"query": "python"})
        assert "brak" in result.lower()
        assert "wewnętrznych" in result.lower()

    def test_queries_all_active_internal_sources(self):
        sources = [
            _search_source("knowledge-base", "internal"),
            _search_source("confluence", "internal"),
        ]
        with (
            patch("mcp.server.list_search_sources", return_value=sources),
            patch("mcp.server.fetch_search_result", side_effect=["wynik KB", "wynik Confluence"]) as mock_fetch,
        ):
            result = MCPServer().call_tool("search_internal", {"query": "backup"})

        assert mock_fetch.call_count == 2
        assert "knowledge-base" in result
        assert "confluence" in result
        assert "wynik KB" in result
        assert "wynik Confluence" in result

    def test_blocked_source_is_skipped(self):
        sources = [
            _search_source("knowledge-base", "internal", is_active=True, is_blocked=False),
            _search_source("poisoned-kb",    "internal", is_active=True, is_blocked=True),
        ]
        with (
            patch("mcp.server.list_search_sources", return_value=sources),
            patch("mcp.server.fetch_search_result", return_value="wynik") as mock_fetch,
        ):
            result = MCPServer().call_tool("search_internal", {"query": "test"})

        assert mock_fetch.call_count == 1
        assert mock_fetch.call_args[0][0] == "knowledge-base"
        assert "poisoned-kb" not in result

    def test_inactive_source_is_skipped(self):
        sources = [
            _search_source("knowledge-base", "internal", is_active=True),
            _search_source("old-kb",         "internal", is_active=False),
        ]
        with (
            patch("mcp.server.list_search_sources", return_value=sources),
            patch("mcp.server.fetch_search_result", return_value="wynik") as mock_fetch,
        ):
            MCPServer().call_tool("search_internal", {"query": "test"})

        assert mock_fetch.call_count == 1
        assert mock_fetch.call_args[0][0] == "knowledge-base"

    def test_passes_internal_type_to_db(self):
        with patch("mcp.server.list_search_sources", return_value=[]) as mock_list:
            MCPServer().call_tool("search_internal", {"query": "test"})
        mock_list.assert_called_once_with("internal")


# ------------------------------------------------------------------
# search_external
# ------------------------------------------------------------------

class TestSearchExternal:
    def test_no_active_external_sources_returns_info(self):
        with patch("mcp.server.list_search_sources", return_value=[]):
            result = MCPServer().call_tool("search_external", {"query": "python"})
        assert "brak" in result.lower()
        assert "zewnętrznych" in result.lower()

    def test_queries_all_active_external_sources(self):
        sources = [
            _search_source("web",       "external"),
            _search_source("tech-docs", "external"),
        ]
        with (
            patch("mcp.server.list_search_sources", return_value=sources),
            patch("mcp.server.fetch_search_result", side_effect=["wynik web", "wynik docs"]) as mock_fetch,
        ):
            result = MCPServer().call_tool("search_external", {"query": "docker"})

        assert mock_fetch.call_count == 2
        assert "web" in result
        assert "tech-docs" in result

    def test_blocked_source_is_skipped(self):
        sources = [
            _search_source("web",          "external", is_active=True, is_blocked=False),
            _search_source("darkweb-index","external", is_active=True, is_blocked=True),
        ]
        with (
            patch("mcp.server.list_search_sources", return_value=sources),
            patch("mcp.server.fetch_search_result", return_value="wynik") as mock_fetch,
        ):
            result = MCPServer().call_tool("search_external", {"query": "test"})

        assert mock_fetch.call_count == 1
        assert mock_fetch.call_args[0][0] == "web"
        assert "darkweb-index" not in result

    def test_passes_external_type_to_db(self):
        with patch("mcp.server.list_search_sources", return_value=[]) as mock_list:
            MCPServer().call_tool("search_external", {"query": "test"})
        mock_list.assert_called_once_with("external")
