"""
Testy integracyjne warstwy DB dla repozytoriów i źródeł GitHub.
Wymagają działającego PostgreSQL z zaaplikowanym schema.sql.

Uruchom: pytest -m integration
Każdy test używa fixtures no_commit_db — żadne dane nie trafiają do bazy.

Najważniejszy test: find_command_output — weryfikuje SQL z dopasowaniem
prefiksowym (komendy z argumentami muszą trafiać w zainstalowane repo).
"""
import pytest

from database.db import (
    add_github_source,
    check_github_source,
    create_repo,
    find_command_output,
    get_repo_by_name,
    get_repo_by_url,
    get_repo_commands,
    list_github_sources,
    list_repos,
    mark_repo_installed,
    mark_repo_uninstalled,
    update_github_source_flags,
)
from database.models import GithubSource, Repository


pytestmark = pytest.mark.integration

# Prefiksy żeby nie kolidować z danymi seed
_OWNER = "test-integration-owner"
_URL   = "github.com/test-integration-owner/test-repo"
_NAME  = "test-integration-repo"


# ------------------------------------------------------------------
# Helpers — insert bezpośrednio przez psycopg2 (poza warstwą db.py)
# ------------------------------------------------------------------

def _insert_repo_command(conn, repo_id: int, command: str, output: str, description: str = ""):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO repo_commands (repo_id, command, description, output) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (repo_id, command) DO NOTHING",
            (repo_id, command, description, output),
        )


# ------------------------------------------------------------------
# GithubSource CRUD
# ------------------------------------------------------------------

class TestGithubSourceDb:
    def test_add_and_check_roundtrip(self, no_commit_db):
        source = add_github_source(GithubSource(owner=_OWNER, is_verified=True))
        fetched = check_github_source(_OWNER)

        assert fetched is not None
        assert fetched.owner == _OWNER
        assert fetched.is_verified is True
        assert fetched.is_blacklisted is False

    def test_unknown_owner_returns_none(self, no_commit_db):
        result = check_github_source("this-owner-does-not-exist-xyz")
        assert result is None

    def test_update_verified_flag(self, no_commit_db):
        add_github_source(GithubSource(owner=_OWNER, is_verified=False))
        updated = update_github_source_flags(_OWNER, is_verified=True)

        assert updated is True
        source = check_github_source(_OWNER)
        assert source.is_verified is True

    def test_update_blacklist_flag(self, no_commit_db):
        add_github_source(GithubSource(owner=_OWNER))
        update_github_source_flags(_OWNER, is_blacklisted=True)

        source = check_github_source(_OWNER)
        assert source.is_blacklisted is True

    def test_update_nonexistent_owner_returns_false(self, no_commit_db):
        result = update_github_source_flags("no-such-owner-xyz", is_verified=True)
        assert result is False

    def test_list_includes_added_source(self, no_commit_db):
        add_github_source(GithubSource(owner=_OWNER, display_name="Test Org"))
        sources = list_github_sources()
        owners = [s.owner for s in sources]
        assert _OWNER in owners


# ------------------------------------------------------------------
# Repository CRUD
# ------------------------------------------------------------------

class TestRepositoryDb:
    def test_create_and_get_by_name(self, no_commit_db):
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        fetched = get_repo_by_name(_NAME)

        assert fetched is not None
        assert fetched.name == _NAME
        assert fetched.url == _URL
        assert fetched.is_installed is False

    def test_get_by_url(self, no_commit_db):
        create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        fetched = get_repo_by_url(_URL)

        assert fetched is not None
        assert fetched.owner == _OWNER

    def test_get_nonexistent_returns_none(self, no_commit_db):
        assert get_repo_by_name("repo-that-does-not-exist-xyz") is None
        assert get_repo_by_url("github.com/nobody/nothing-xyz") is None

    def test_mark_installed(self, no_commit_db):
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        mark_repo_installed(repo.id)

        updated = get_repo_by_name(_NAME)
        assert updated.is_installed is True
        assert updated.installed_at is not None

    def test_mark_uninstalled(self, no_commit_db):
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        mark_repo_installed(repo.id)
        mark_repo_uninstalled(repo.id)

        updated = get_repo_by_name(_NAME)
        assert updated.is_installed is False
        assert updated.installed_at is None

    def test_list_repos_includes_created(self, no_commit_db):
        create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        repos = list_repos()
        names = [r.name for r in repos]
        assert _NAME in names


# ------------------------------------------------------------------
# find_command_output — kluczowy test SQL
# ------------------------------------------------------------------

class TestFindCommandOutput:
    def _setup_installed_repo_with_command(self, conn, command: str, output: str) -> int:
        """Tworzy zainstalowane repo z jedną komendą. Zwraca repo_id."""
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        mark_repo_installed(repo.id)
        _insert_repo_command(conn, repo.id, command, output)
        return repo.id

    def test_exact_command_match(self, no_commit_db):
        self._setup_installed_repo_with_command(
            no_commit_db, "meeting-scheduler --list", "lista spotkań"
        )
        result = find_command_output("meeting-scheduler --list")
        assert result == "lista spotkań"

    def test_prefix_match_with_args(self, no_commit_db):
        """Komenda 'meeting-scheduler' powinna pasować do wywołania z argumentami."""
        self._setup_installed_repo_with_command(
            no_commit_db, "meeting-scheduler", "output spotkań"
        )
        result = find_command_output("meeting-scheduler --date 2026-06-01 --title standup")
        assert result == "output spotkań"

    def test_prefix_match_exact_boundary(self, no_commit_db):
        """'backup' nie może pasować do 'backup-tool' — wymaga spacji lub końca."""
        self._setup_installed_repo_with_command(
            no_commit_db, "backup-tool", "kopia zapasowa"
        )
        result = find_command_output("backup")
        assert result is None

    def test_uninstalled_repo_not_matched(self, no_commit_db):
        """Komendy z niezainstalowanych repo nie powinny być zwracane."""
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        # is_installed = FALSE — nie wywołujemy mark_repo_installed
        _insert_repo_command(no_commit_db, repo.id, "my-tool", "secret output")

        result = find_command_output("my-tool")
        assert result is None

    def test_returns_none_when_no_installed_repos(self, no_commit_db):
        result = find_command_output("anything")
        assert result is None

    def test_longest_match_wins(self, no_commit_db):
        """Gdy są dwie pasujące komendy, dłuższa (bardziej specyficzna) wygrywa."""
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        mark_repo_installed(repo.id)
        _insert_repo_command(no_commit_db, repo.id, "tool", "krótkie dopasowanie")
        _insert_repo_command(no_commit_db, repo.id, "tool --verbose", "długie dopasowanie")

        result = find_command_output("tool --verbose --output json")
        assert result == "długie dopasowanie"


# ------------------------------------------------------------------
# get_repo_commands
# ------------------------------------------------------------------

class TestGetRepoCommands:
    def test_returns_commands_for_repo(self, no_commit_db):
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        _insert_repo_command(no_commit_db, repo.id, "cmd-a", "out-a")
        _insert_repo_command(no_commit_db, repo.id, "cmd-b", "out-b")

        cmds = get_repo_commands(repo.id)
        commands = [c.command for c in cmds]
        assert "cmd-a" in commands
        assert "cmd-b" in commands

    def test_returns_empty_for_repo_without_commands(self, no_commit_db):
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        cmds = get_repo_commands(repo.id)
        assert cmds == []

    def test_commands_sorted_alphabetically(self, no_commit_db):
        repo = create_repo(Repository(name=_NAME, url=_URL, owner=_OWNER))
        _insert_repo_command(no_commit_db, repo.id, "z-last", "")
        _insert_repo_command(no_commit_db, repo.id, "a-first", "")

        cmds = get_repo_commands(repo.id)
        assert cmds[0].command == "a-first"
        assert cmds[1].command == "z-last"
