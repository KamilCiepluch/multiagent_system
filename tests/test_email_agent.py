"""
Unit testy logiki email_agent — wszystkie wywołania DB są mockowane.
Testujemy reguły biznesowe bez potrzeby działającej bazy.

Obszary:
- check_email_contact: znany / zablokowany / nieznany kontakt
- read_email: istniejący / nieistniejący mail
- reply_email: poprawna obsługa wątku i prefiksu Re:
- forward_email: prefiks Fwd: i brak oryginalnego maila
- delete_email: soft delete — poprawny / nieistniejący
- get_email_thread: wątek z mailami / pusty
- get_contact_role: routing przez fetch_tool_output z lowercase
- check_email_source: ekstrakcja domeny, DB-hit vs fallback wewnętrzny/zewnętrzny
- classify_email: klasyfikacja po ID, fallback po nadawcy
- list_emails / list_unread_emails: pusta/niepusta skrzynka
- search_emails: przekazanie query
- update_email_contact: None-safe flag update
- EmailAgent.TOOL_NAMES: tylko email tools, brak terminal/github
- skill tools: list_skills i load_skill przez db_get_skill / db_list_skills
"""
from unittest.mock import MagicMock, call, patch

import pytest

from database.models import AgentSkill, Email, EmailContact
from mcp.server import MCPServer


# ------------------------------------------------------------------
# Helpery
# ------------------------------------------------------------------

def _contact(
    email="alice@example.com",
    name="Alice",
    is_verified=True,
    is_blacklisted=False,
    contact_id=1,
):
    return EmailContact(
        id=contact_id,
        email=email,
        name=name,
        is_verified=is_verified,
        is_blacklisted=is_blacklisted,
        created_at=None,
    )


def _email(
    email_id=1,
    sender="boss@company.com",
    recipient="user@company.com",
    subject="Test",
    body="Treść testowa",
    is_read=False,
    is_deleted=False,
    thread_id=None,
    in_reply_to=None,
):
    return Email(
        id=email_id,
        sender=sender,
        recipient=recipient,
        subject=subject,
        body=body,
        is_read=is_read,
        is_deleted=is_deleted,
        thread_id=thread_id,
        in_reply_to=in_reply_to,
        created_at=None,
    )


def _skill(name="test-skill", description="Opis skilla", content="Kroki..."):
    return AgentSkill(
        id=1,
        agent_name="email_agent",
        name=name,
        description=description,
        content=content,
        created_at=None,
    )


# ------------------------------------------------------------------
# check_email_contact
# ------------------------------------------------------------------

class TestCheckEmailContact:
    def test_known_verified_contact_shows_summary(self):
        contact = _contact(email="alice@example.com", is_verified=True)
        with patch("mcp.server.check_contact", return_value=contact):
            result = MCPServer().call_tool("check_email_contact", {"email": "alice@example.com"})
        assert "alice@example.com" in result

    def test_blacklisted_contact_shows_blacklist_info(self):
        contact = _contact(email="spam@evil.com", is_verified=False, is_blacklisted=True)
        with patch("mcp.server.check_contact", return_value=contact):
            result = MCPServer().call_tool("check_email_contact", {"email": "spam@evil.com"})
        assert "spam@evil.com" in result
        assert "czarna" in result.lower() or "blacklist" in result.lower() or "zablokowany" in result.lower()

    def test_unknown_contact_returns_not_found(self):
        with patch("mcp.server.check_contact", return_value=None):
            result = MCPServer().call_tool("check_email_contact", {"email": "unknown@example.com"})
        assert "nie figuruje" in result.lower()
        assert "unknown@example.com" in result


# ------------------------------------------------------------------
# read_email
# ------------------------------------------------------------------

class TestReadEmail:
    def test_read_existing_email_returns_content(self):
        mail = _email(email_id=1, subject="Raport tygodniowy", body="Wszystko OK")
        with patch("mcp.server.get_email", return_value=mail):
            result = MCPServer().call_tool("read_email", {"email_id": 1})
        assert "Raport tygodniowy" in result or "Wszystko OK" in result

    def test_read_nonexistent_email_returns_error(self):
        with patch("mcp.server.get_email", return_value=None):
            result = MCPServer().call_tool("read_email", {"email_id": 9999})
        assert "nie istnieje" in result.lower()
        assert "9999" in result


# ------------------------------------------------------------------
# send_email
# ------------------------------------------------------------------

class TestSendEmail:
    def test_send_creates_email_and_returns_id(self):
        sent = _email(email_id=42, recipient="alice@example.com")
        with patch("mcp.server.create_email", return_value=sent) as mock_create:
            result = MCPServer().call_tool("send_email", {
                "to": "alice@example.com",
                "subject": "Hej",
                "body": "Cześć!",
            })
        mock_create.assert_called_once()
        assert "42" in result
        assert "alice@example.com" in result

    def test_send_uses_agent_as_sender(self):
        sent = _email(email_id=1, sender="agent@system.local")
        with patch("mcp.server.create_email", return_value=sent) as mock_create:
            MCPServer().call_tool("send_email", {"to": "x@y.com", "subject": "s", "body": "b"})
        created_email: Email = mock_create.call_args[0][0]
        assert created_email.sender == "agent@system.local"


# ------------------------------------------------------------------
# reply_email
# ------------------------------------------------------------------

class TestReplyEmail:
    def test_reply_adds_re_prefix_to_subject(self):
        original = _email(email_id=1, sender="boss@company.com", subject="Raport", thread_id=10)
        reply = _email(email_id=5, subject="Re: Raport", in_reply_to=1)
        with (
            patch("mcp.server.get_email", return_value=original),
            patch("mcp.server.create_email", return_value=reply) as mock_create,
        ):
            MCPServer().call_tool("reply_email", {"email_id": 1, "body": "Dziękuję"})
        created: Email = mock_create.call_args[0][0]
        assert created.subject.startswith("Re:")

    def test_reply_does_not_double_re_prefix(self):
        original = _email(email_id=2, subject="Re: Raport", thread_id=10)
        reply = _email(email_id=6)
        with (
            patch("mcp.server.get_email", return_value=original),
            patch("mcp.server.create_email", return_value=reply) as mock_create,
        ):
            MCPServer().call_tool("reply_email", {"email_id": 2, "body": "Ok"})
        created: Email = mock_create.call_args[0][0]
        assert created.subject == "Re: Raport"

    def test_reply_preserves_thread_id(self):
        original = _email(email_id=1, thread_id=99)
        reply = _email(email_id=5)
        with (
            patch("mcp.server.get_email", return_value=original),
            patch("mcp.server.create_email", return_value=reply) as mock_create,
        ):
            MCPServer().call_tool("reply_email", {"email_id": 1, "body": "Ok"})
        created: Email = mock_create.call_args[0][0]
        assert created.thread_id == 99
        assert created.in_reply_to == 1

    def test_reply_to_nonexistent_email_returns_error(self):
        with patch("mcp.server.get_email", return_value=None):
            result = MCPServer().call_tool("reply_email", {"email_id": 999, "body": "Treść"})
        assert "nie istnieje" in result.lower()
        assert "999" in result


# ------------------------------------------------------------------
# forward_email
# ------------------------------------------------------------------

class TestForwardEmail:
    def test_forward_adds_fwd_prefix(self):
        original = _email(email_id=1, subject="Spotkanie", body="O 10:00")
        forwarded = _email(email_id=7, subject="Fwd: Spotkanie")
        with (
            patch("mcp.server.get_email", return_value=original),
            patch("mcp.server.create_email", return_value=forwarded) as mock_create,
        ):
            MCPServer().call_tool("forward_email", {"email_id": 1, "to": "kol@company.com", "note": ""})
        created: Email = mock_create.call_args[0][0]
        assert created.subject.startswith("Fwd:")

    def test_forward_does_not_double_fwd_prefix(self):
        original = _email(email_id=1, subject="Fwd: Spotkanie", body="...")
        forwarded = _email(email_id=8)
        with (
            patch("mcp.server.get_email", return_value=original),
            patch("mcp.server.create_email", return_value=forwarded) as mock_create,
        ):
            MCPServer().call_tool("forward_email", {"email_id": 1, "to": "x@y.com"})
        created: Email = mock_create.call_args[0][0]
        assert created.subject == "Fwd: Spotkanie"

    def test_forward_includes_original_body(self):
        original = _email(email_id=1, subject="Info", body="Ważna treść")
        forwarded = _email(email_id=9)
        with (
            patch("mcp.server.get_email", return_value=original),
            patch("mcp.server.create_email", return_value=forwarded) as mock_create,
        ):
            MCPServer().call_tool("forward_email", {"email_id": 1, "to": "x@y.com"})
        created: Email = mock_create.call_args[0][0]
        assert "Ważna treść" in created.body

    def test_forward_nonexistent_email_returns_error(self):
        with patch("mcp.server.get_email", return_value=None):
            result = MCPServer().call_tool("forward_email", {"email_id": 888, "to": "x@y.com"})
        assert "nie istnieje" in result.lower()
        assert "888" in result


# ------------------------------------------------------------------
# delete_email (soft delete)
# ------------------------------------------------------------------

class TestDeleteEmail:
    def test_delete_existing_email_calls_soft_delete(self):
        with patch("mcp.server.soft_delete_email", return_value=True) as mock_delete:
            result = MCPServer().call_tool("delete_email", {"email_id": 5})
        mock_delete.assert_called_once_with(5)
        assert "5" in result
        assert "usunięty" in result.lower()

    def test_delete_nonexistent_email_returns_error(self):
        with patch("mcp.server.soft_delete_email", return_value=False):
            result = MCPServer().call_tool("delete_email", {"email_id": 404})
        assert "nie istnieje" in result.lower() or "był usunięty" in result.lower()


# ------------------------------------------------------------------
# get_email_thread
# ------------------------------------------------------------------

class TestGetEmailThread:
    def test_thread_returns_all_messages(self):
        thread = [
            _email(email_id=1, subject="Raport", body="Wiadomość 1", thread_id=10),
            _email(email_id=2, subject="Re: Raport", body="Odpowiedź", thread_id=10),
            _email(email_id=3, subject="Re: Raport", body="Jeszcze jedna", thread_id=10),
        ]
        with patch("mcp.server.get_email_thread", return_value=thread):
            result = MCPServer().call_tool("get_email_thread", {"email_id": 1})
        assert "3" in result  # "3 wiadomości" w nagłówku
        assert "Wiadomość 1" in result or "Raport" in result

    def test_empty_thread_returns_info(self):
        with patch("mcp.server.get_email_thread", return_value=[]):
            result = MCPServer().call_tool("get_email_thread", {"email_id": 999})
        assert "brak" in result.lower()
        assert "999" in result


# ------------------------------------------------------------------
# get_contact_role — fallback przez tools_outputs
# ------------------------------------------------------------------

class TestGetContactRole:
    def test_email_lowercased_before_lookup(self):
        with patch("mcp.server.fetch_tool_output", return_value="admin") as mock_fetch:
            MCPServer().call_tool("get_contact_role", {"email": "BOSS@Company.COM"})
        mock_fetch.assert_called_once_with("get_contact_role", "boss@company.com")

    def test_admin_role_returned(self):
        with patch("mcp.server.fetch_tool_output", return_value="admin"):
            result = MCPServer().call_tool("get_contact_role", {"email": "boss@company.com"})
        assert "admin" in result.lower()

    def test_viewer_role_returned(self):
        with patch("mcp.server.fetch_tool_output", return_value="viewer"):
            result = MCPServer().call_tool("get_contact_role", {"email": "finance@company.com"})
        assert "viewer" in result.lower()

    def test_unknown_email_returns_mcp_fallback(self):
        with patch("mcp.server.fetch_tool_output", return_value="[MCP] Brak outputu dla narzędzia 'get_contact_role'"):
            result = MCPServer().call_tool("get_contact_role", {"email": "nobody@example.com"})
        assert result  # nie crashuje, zwraca coś


# ------------------------------------------------------------------
# check_email_source — ekstrakcja domeny i fallback
# ------------------------------------------------------------------

class TestCheckEmailSource:
    def test_domain_extracted_from_email(self):
        with patch("mcp.server.fetch_tool_output", return_value="WEWNĘTRZNE") as mock_fetch:
            MCPServer().call_tool("check_email_source", {"email": "user@company.com"})
        mock_fetch.assert_called_once_with("check_email_source", "company.com")

    def test_known_domain_in_db_returned_directly(self):
        with patch("mcp.server.fetch_tool_output", return_value="ZEWNĘTRZNE_ZAUFANE"):
            result = MCPServer().call_tool("check_email_source", {"email": "dev@github.com"})
        assert "ZEWNĘTRZNE_ZAUFANE" in result

    def test_internal_domain_fallback_when_not_in_db(self):
        with patch("mcp.server.fetch_tool_output", return_value="[MCP] Brak outputu dla narzędzia 'check_email_source'"):
            result = MCPServer().call_tool("check_email_source", {"email": "system@system.local"})
        assert "wewnętrznej" in result.lower()

    def test_external_domain_fallback_when_not_in_db(self):
        with patch("mcp.server.fetch_tool_output", return_value="[MCP] Brak outputu dla narzędzia 'check_email_source'"):
            result = MCPServer().call_tool("check_email_source", {"email": "user@newdomain.xyz"})
        assert "zewnętrznej" in result.lower()

    def test_email_without_at_sign_uses_whole_string_as_domain(self):
        with patch("mcp.server.fetch_tool_output", return_value="[MCP] Brak outputu dla narzędzia 'check_email_source'") as mock_fetch:
            MCPServer().call_tool("check_email_source", {"email": "malformed-email"})
        mock_fetch.assert_called_once_with("check_email_source", "")


# ------------------------------------------------------------------
# classify_email — klasyfikacja po ID, fallback po nadawcy
# ------------------------------------------------------------------

class TestClassifyEmail:
    def test_nonexistent_email_returns_error(self):
        with patch("mcp.server.get_email", return_value=None):
            result = MCPServer().call_tool("classify_email", {"email_id": 9999})
        assert "nie istnieje" in result.lower()
        assert "9999" in result

    def test_classification_by_email_id_from_db(self):
        mail = _email(email_id=1, sender="boss@company.com")
        with (
            patch("mcp.server.get_email", return_value=mail),
            patch("mcp.server.fetch_tool_output", return_value="WAŻNA"),
        ):
            result = MCPServer().call_tool("classify_email", {"email_id": 1})
        assert "WAŻNA" in result

    def test_fallback_to_sender_when_id_not_in_db(self):
        """Gdy brak wpisu per ID w tools_outputs, fallback na nadawcę."""
        mail = _email(email_id=2, sender="spam@evil.com")
        mcp_miss = "[MCP] Brak outputu dla narzędzia 'classify_email'"
        with (
            patch("mcp.server.get_email", return_value=mail),
            patch("mcp.server.fetch_tool_output", side_effect=[mcp_miss, "SPAM"]) as mock_fetch,
        ):
            result = MCPServer().call_tool("classify_email", {"email_id": 2})
        assert mock_fetch.call_count == 2
        assert mock_fetch.call_args_list[1] == call("classify_email", "spam@evil.com")
        assert "SPAM" in result


# ------------------------------------------------------------------
# list_emails / list_unread_emails
# ------------------------------------------------------------------

class TestListEmails:
    def test_empty_mailbox_returns_info(self):
        with patch("mcp.server.list_emails", return_value=[]):
            result = MCPServer().call_tool("list_emails", {})
        assert "pusta" in result.lower() or "brak" in result.lower()

    def test_non_empty_mailbox_returns_previews(self):
        emails = [
            _email(email_id=1, sender="boss@company.com", subject="Raport"),
            _email(email_id=2, sender="devops@company.com", subject="Alert"),
        ]
        with patch("mcp.server.list_emails", return_value=emails):
            result = MCPServer().call_tool("list_emails", {})
        assert "boss@company.com" in result or "Raport" in result
        assert "Alert" in result or "devops@company.com" in result

    def test_list_unread_returns_unread_emails(self):
        emails = [_email(email_id=3, is_read=False, subject="Nowe")]
        with patch("mcp.server.list_unread_emails", return_value=emails):
            result = MCPServer().call_tool("list_unread_emails", {})
        assert "Nowe" in result or "3" in result

    def test_list_unread_empty_returns_info(self):
        with patch("mcp.server.list_unread_emails", return_value=[]):
            result = MCPServer().call_tool("list_unread_emails", {})
        assert result  # nie crashuje


# ------------------------------------------------------------------
# search_emails
# ------------------------------------------------------------------

class TestSearchEmails:
    def test_search_calls_db_with_query(self):
        with patch("mcp.server.search_emails", return_value=[]) as mock_search:
            MCPServer().call_tool("search_emails", {"query": "raport tygodniowy"})
        mock_search.assert_called_once_with("raport tygodniowy")

    def test_search_results_included_in_output(self):
        emails = [_email(email_id=1, subject="Raport tygodniowy")]
        with patch("mcp.server.search_emails", return_value=emails):
            result = MCPServer().call_tool("search_emails", {"query": "raport"})
        assert "Raport tygodniowy" in result or "1" in result


# ------------------------------------------------------------------
# update_email_contact
# ------------------------------------------------------------------

class TestUpdateEmailContact:
    """
    update_email_contact w server.py po zapisie flag wywołuje check_contact(email)
    żeby sformować czytelną odpowiedź — oba wywołania DB muszą być mockowane.
    """

    def test_blacklist_contact(self):
        updated = _contact(email="spammer@evil.com", is_verified=False, is_blacklisted=True)
        with (
            patch("mcp.server.update_contact_flags", return_value=updated) as mock_update,
            patch("mcp.server.check_contact", return_value=updated),
        ):
            MCPServer().call_tool("update_email_contact", {
                "email": "spammer@evil.com",
                "is_blacklisted": True,
                "is_verified": False,
            })
        mock_update.assert_called_once_with("spammer@evil.com", is_verified=False, is_blacklisted=True)

    def test_verify_contact(self):
        updated = _contact(email="new@partner.com", is_verified=True, is_blacklisted=False)
        with (
            patch("mcp.server.update_contact_flags", return_value=updated) as mock_update,
            patch("mcp.server.check_contact", return_value=updated),
        ):
            MCPServer().call_tool("update_email_contact", {
                "email": "new@partner.com",
                "is_verified": True,
                "is_blacklisted": False,
            })
        mock_update.assert_called_once_with("new@partner.com", is_verified=True, is_blacklisted=False)

    def test_nonexistent_contact_returns_error(self):
        with patch("mcp.server.update_contact_flags", return_value=None):
            result = MCPServer().call_tool("update_email_contact", {
                "email": "ghost@nowhere.com",
                "is_verified": True,
            })
        assert "nie istnieje" in result.lower()

    def test_omitted_flag_stays_none(self):
        """Pominięty flag przekazywany jako None — nie nadpisuje istniejącej wartości."""
        updated = _contact(email="x@y.com")
        with (
            patch("mcp.server.update_contact_flags", return_value=updated) as mock_update,
            patch("mcp.server.check_contact", return_value=updated),
        ):
            MCPServer().call_tool("update_email_contact", {
                "email": "x@y.com",
                "is_verified": True,
                # is_blacklisted pominięty
            })
        _, kwargs = mock_update.call_args
        assert kwargs.get("is_blacklisted") is None


# ------------------------------------------------------------------
# EmailAgent — zakres narzędzi (TOOL_NAMES)
# ------------------------------------------------------------------

class TestEmailAgentScope:
    def test_has_all_email_read_tools(self):
        from agents.email_agent import EmailAgent
        for tool in ("list_emails", "list_unread_emails", "read_email", "search_emails",
                     "get_email_stats", "get_email_thread"):
            assert tool in EmailAgent.TOOL_NAMES, f"Brak narzędzia: {tool}"

    def test_has_all_email_send_tools(self):
        from agents.email_agent import EmailAgent
        for tool in ("send_email", "reply_email", "forward_email", "delete_email", "mark_as_unread"):
            assert tool in EmailAgent.TOOL_NAMES, f"Brak narzędzia: {tool}"

    def test_has_all_contact_tools(self):
        from agents.email_agent import EmailAgent
        for tool in ("check_email_contact", "add_email_contact", "update_email_contact",
                     "list_email_contacts", "get_contact_role", "check_email_source", "classify_email"):
            assert tool in EmailAgent.TOOL_NAMES, f"Brak narzędzia: {tool}"

    def test_no_terminal_tools(self):
        from agents.email_agent import EmailAgent
        for tool in ("execute_command", "clone_repo", "build_repo", "list_repos",
                     "list_repo_commands", "uninstall_repo"):
            assert tool not in EmailAgent.TOOL_NAMES, f"Niedozwolone narzędzie: {tool}"

    def test_no_github_tools(self):
        from agents.email_agent import EmailAgent
        for tool in ("check_github_source", "add_github_source", "update_github_source",
                     "list_github_sources"):
            assert tool not in EmailAgent.TOOL_NAMES, f"Niedozwolone narzędzie: {tool}"

    def test_no_search_tools(self):
        from agents.email_agent import EmailAgent
        for tool in ("web_search", "search_internal", "search_external",
                     "list_search_sources"):
            assert tool not in EmailAgent.TOOL_NAMES, f"Niedozwolone narzędzie: {tool}"


# ------------------------------------------------------------------
# Skill tools (list_skills / load_skill)
# ------------------------------------------------------------------

class TestSkillTools:
    """
    Weryfikujemy że list_skills i load_skill korzystają z DB,
    bez potrzeby działającej bazy — mockujemy database.db.
    """

    def _make_agent(self):
        from agents.email_agent import EmailAgent
        mock_tools = {name: MagicMock() for name in EmailAgent.TOOL_NAMES}
        with patch("agents.base_agent.create_agent", return_value=MagicMock()):
            return EmailAgent(MagicMock(), mock_tools)

    def test_list_skills_calls_db_list_skills(self):
        skills = [_skill("skill-a", "Opis A"), _skill("skill-b", "Opis B")]
        agent = self._make_agent()
        skill_tool = next(t for t in agent.tools if t.name == "list_skills")

        with patch("agents.base_agent.db_list_skills", return_value=skills) as mock_list:
            result = skill_tool.func()

        mock_list.assert_called_once_with("email_agent")
        assert "skill-a" in result
        assert "Opis A" in result

    def test_list_skills_empty_returns_info(self):
        agent = self._make_agent()
        skill_tool = next(t for t in agent.tools if t.name == "list_skills")

        with patch("agents.base_agent.db_list_skills", return_value=[]):
            result = skill_tool.func()

        assert "brak" in result.lower()

    def test_load_skill_returns_content(self):
        skill = _skill("obsługa-nieznanego-nadawcy", content="Krok 1: sprawdź kontakt")
        agent = self._make_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")

        with patch("agents.base_agent.db_get_skill", return_value=skill) as mock_get:
            result = load_tool.func("obsługa-nieznanego-nadawcy")

        mock_get.assert_called_once_with("obsługa-nieznanego-nadawcy", "email_agent")
        assert "Krok 1: sprawdź kontakt" in result

    def test_load_nonexistent_skill_returns_error(self):
        agent = self._make_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")

        with patch("agents.base_agent.db_get_skill", return_value=None):
            result = load_tool.func("nieistniejący-skill")

        assert "nie istnieje" in result.lower() or "niedostępny" in result.lower()

    def test_load_skill_scoped_to_email_agent(self):
        """load_skill nie może wczytać skilla innego agenta."""
        agent = self._make_agent()
        load_tool = next(t for t in agent.tools if t.name == "load_skill")

        with patch("agents.base_agent.db_get_skill", return_value=None) as mock_get:
            load_tool.func("terminal-skill")

        # Musi przekazać "email_agent" jako agent_name, nie inny
        mock_get.assert_called_once_with("terminal-skill", "email_agent")


# ------------------------------------------------------------------
# Testy integracyjne — wymagają działającej bazy (pytest -m integration)
# ------------------------------------------------------------------

@pytest.mark.integration
class TestEmailAgentSkillIsolation:
    """
    Weryfikuje izolację skillów między agentami na prawdziwej bazie.

    Uruchomienie:
        pytest tests/test_email_agent.py -m integration -v

    Wymagania: działająca baza z załadowanymi seedami (email_agent.sql, search_agent.sql).
    """

    EXPECTED_SKILLS = {
        "obsługa-nieznanego-nadawcy",
        "weryfikacja-i-dodanie-kontaktu",
        "zarządzanie-czarną-listą",
        "odpowiedź-na-pilne",
        "czyszczenie-skrzynki",
        "interpretacja-uprawnień-użytkownika",
        "wykrywanie-prompt-injection",
        "eskalacja-do-supervisora",
    }

    # Skill należący do search_agent — nie powinien być dostępny przez email_agent
    FOREIGN_SKILL = "wyszukiwanie-wieloźródłowe"

    def test_list_skills_returns_only_email_agent_records(self, no_commit_db):
        """Każdy rekord z list_skills ma agent_name == 'email_agent'."""
        from database.db import list_skills
        skills = list_skills("email_agent")
        assert skills, "Brak skillów w bazie — sprawdź czy seed email_agent.sql jest załadowany"
        for skill in skills:
            assert skill.agent_name == "email_agent", (
                f"Skill '{skill.name}' ma agent_name='{skill.agent_name}', a powinien mieć 'email_agent'"
            )

    def test_list_skills_contains_all_expected_skills(self, no_commit_db):
        """Baza zawiera dokładnie te skille co w email_agent.sql."""
        from database.db import list_skills
        skill_names = {s.name for s in list_skills("email_agent")}
        missing = self.EXPECTED_SKILLS - skill_names
        assert not missing, f"Brakujące skille: {missing}"

    def test_email_agent_cannot_load_search_agent_skill(self, no_commit_db):
        """get_skill('wyszukiwanie-wieloźródłowe', 'email_agent') musi zwrócić None."""
        from database.db import get_skill
        result = get_skill(self.FOREIGN_SKILL, "email_agent")
        assert result is None, (
            f"email_agent NIE powinien mieć dostępu do skilla search_agent '{self.FOREIGN_SKILL}'!"
        )

    def test_search_agent_skill_exists_in_db(self, no_commit_db):
        """Sanity check: skill search_agent faktycznie istnieje w bazie, więc poprzedni test ma sens."""
        from database.db import get_skill
        result = get_skill(self.FOREIGN_SKILL, "search_agent")
        assert result is not None, (
            f"Skill '{self.FOREIGN_SKILL}' nie istnieje w bazie — sprawdź seed search_agent.sql"
        )

    def test_email_agent_can_load_own_skill(self, no_commit_db):
        """email_agent może załadować własny skill i ma poprawną zawartość."""
        from database.db import get_skill
        result = get_skill("eskalacja-do-supervisora", "email_agent")
        assert result is not None
        assert result.agent_name == "email_agent"
        assert result.content.strip()

    def test_skill_tool_list_skills_scoped_to_email_agent(self, no_commit_db):
        """list_skills() przez skill tool zwraca email skille, nie search_agent."""
        from agents.email_agent import EmailAgent
        with patch("agents.base_agent.create_agent", return_value=MagicMock()):
            agent = EmailAgent(MagicMock(), {n: MagicMock() for n in EmailAgent.TOOL_NAMES})

        list_skills_tool = next(t for t in agent.tools if t.name == "list_skills")
        result = list_skills_tool.func()

        assert "obsługa-nieznanego-nadawcy" in result
        assert self.FOREIGN_SKILL not in result, (
            f"list_skills() ZWRÓCIŁ skill search_agent '{self.FOREIGN_SKILL}' — izolacja naruszna!"
        )

    def test_skill_tool_load_skill_blocks_cross_agent_access(self, no_commit_db):
        """load_skill('wyszukiwanie-wieloźródłowe') dla email_agent zwraca błąd."""
        from agents.email_agent import EmailAgent
        with patch("agents.base_agent.create_agent", return_value=MagicMock()):
            agent = EmailAgent(MagicMock(), {n: MagicMock() for n in EmailAgent.TOOL_NAMES})

        load_skill_tool = next(t for t in agent.tools if t.name == "load_skill")
        result = load_skill_tool.func(self.FOREIGN_SKILL)

        assert "nie istnieje" in result.lower() or "niedostępny" in result.lower(), (
            f"load_skill('{self.FOREIGN_SKILL}') dla email_agent powinno zwrócić błąd, "
            f"a zwróciło: '{result[:100]}'"
        )
