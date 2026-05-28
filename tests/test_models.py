"""
Czyste unit testy modeli Pydantic — zero zależności od bazy ani serwera.
Testują metody as_summary / as_preview / as_full które są używane przez MCP server
do formatowania odpowiedzi zwracanych agentom.
"""
from datetime import datetime

import pytest

from database.models import GithubSource, Repository, RepoCommand, Email, EmailContact


# ------------------------------------------------------------------
# GithubSource
# ------------------------------------------------------------------

class TestGithubSourceSummary:
    def test_verified_shows_label(self):
        s = GithubSource(owner="company", is_verified=True)
        assert "zweryfikowany" in s.as_summary()

    def test_blacklisted_shows_label(self):
        s = GithubSource(owner="badactor", is_blacklisted=True)
        assert "CZARNA LISTA" in s.as_summary()

    def test_no_flags_shows_unknown(self):
        s = GithubSource(owner="stranger")
        assert "nieznany" in s.as_summary()

    def test_display_name_included(self):
        s = GithubSource(owner="corp", display_name="Corp Inc.", is_verified=True)
        assert "Corp Inc." in s.as_summary()

    def test_owner_prefixed_with_github(self):
        s = GithubSource(owner="myorg")
        assert "github/myorg" in s.as_summary()

    def test_verified_and_blacklisted_shows_both(self):
        # edge case — nie powinno się zdarzyć w praktyce, ale model na to pozwala
        s = GithubSource(owner="weird", is_verified=True, is_blacklisted=True)
        summary = s.as_summary()
        assert "zweryfikowany" in summary
        assert "CZARNA LISTA" in summary


# ------------------------------------------------------------------
# Repository
# ------------------------------------------------------------------

class TestRepositorySummary:
    def test_installed_shows_status(self):
        r = Repository(
            id=1, name="my-tool", url="github.com/org/my-tool", owner="org",
            is_installed=True, installed_at=datetime(2026, 5, 29, 10, 0),
        )
        assert "zainstalowane" in r.as_summary()

    def test_not_installed_shows_cloned(self):
        r = Repository(id=2, name="other", url="github.com/org/other", owner="org")
        assert "sklonowane" in r.as_summary()

    def test_description_included(self):
        r = Repository(
            id=3, name="x", url="github.com/a/x", owner="a",
            description="Narzędzie do backupu",
        )
        assert "Narzędzie do backupu" in r.as_summary()

    def test_url_in_summary(self):
        r = Repository(id=4, name="y", url="github.com/b/y", owner="b")
        assert "github.com/b/y" in r.as_summary()

    def test_installed_at_timestamp_visible(self):
        r = Repository(
            id=5, name="z", url="github.com/c/z", owner="c",
            is_installed=True, installed_at=datetime(2026, 5, 29, 14, 30),
        )
        assert "2026-05-29" in r.as_summary()


# ------------------------------------------------------------------
# RepoCommand
# ------------------------------------------------------------------

class TestRepoCommandSummary:
    def test_command_prefixed_with_dollar(self):
        cmd = RepoCommand(repo_id=1, command="meeting-scheduler --list", output="ok")
        assert "$ meeting-scheduler --list" in cmd.as_summary()

    def test_description_included(self):
        cmd = RepoCommand(
            repo_id=1, command="backup.sh",
            description="Tworzenie kopii zapasowej", output="done",
        )
        assert "Tworzenie kopii zapasowej" in cmd.as_summary()

    def test_no_description_still_valid(self):
        cmd = RepoCommand(repo_id=1, command="run.sh", output="ok")
        summary = cmd.as_summary()
        assert "$ run.sh" in summary
        assert summary  # nie pusty


# ------------------------------------------------------------------
# Email (istniejące modele — regresja)
# ------------------------------------------------------------------

class TestEmailModels:
    def test_preview_shows_sender(self):
        e = Email(id=1, sender="boss@co.com", subject="Spotkanie")
        assert "boss@co.com" in e.as_preview()

    def test_preview_unread_label(self):
        e = Email(id=1, sender="x@y.com", is_read=False)
        assert "nowy" in e.as_preview()

    def test_preview_read_label(self):
        e = Email(id=1, sender="x@y.com", is_read=True)
        assert "przeczytany" in e.as_preview()

    def test_contact_verified_label(self):
        c = EmailContact(email="a@b.com", is_verified=True)
        assert "zweryfikowany" in c.as_summary()

    def test_contact_blacklisted_label(self):
        c = EmailContact(email="spam@evil.com", is_blacklisted=True)
        assert "CZARNA LISTA" in c.as_summary()
