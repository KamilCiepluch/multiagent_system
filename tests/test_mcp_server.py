"""
Unit testy logiki MCP server — wszystkie wywołania DB są mockowane.
Testujemy reguły biznesowe bez potrzeby działającej bazy.

Kluczowe scenariusze:
- clone_repo: blokowanie niezweryfikowanych / nieznanych / czarnolistowych właścicieli
- execute_command: komendy z repo mają pierwszeństwo przed tools_outputs
- build_repo: instalacja i aktywacja komend
"""
from unittest.mock import MagicMock, call, patch

import pytest

from database.models import GithubSource, RepoCommand, Repository
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
            patch("mcp.server.create_repo", return_value=_repo(name="my-tool")) as mock_create,
        ):
            MCPServer().call_tool("clone_repo", {"url": "github.com/org/my-tool"})

        created_repo: Repository = mock_create.call_args[0][0]
        assert created_repo.name == "my-tool"

    def test_explicit_name_overrides_url(self):
        with (
            patch("mcp.server.check_github_source", return_value=_source()),
            patch("mcp.server.get_repo_by_url", return_value=None),
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
            result = MCPServer().call_tool("execute_command", {"command": "ls -la"})

        assert result == "output z bazy"
        mock_fetch.assert_called_once_with("execute_command", "ls -la")

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
