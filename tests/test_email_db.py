"""
Testy integracyjne email agenta — prawdziwa baza, prawdziwy SQL.

Każdy test dostaje świeżo seedowaną bazę (rollback po zakończeniu).
Weryfikujemy że db.py i MCPServer produkują poprawne wyniki
gdy agent wywoła narzędzia z właściwymi argumentami.

Uruchomienie:
    pytest tests/test_email_db.py -v

Wymagania: PostgreSQL dostępny pod adresem z config.py.
Baza testowa 'agent_benchmark_test' jest tworzona i niszczona automatycznie.
"""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from config import settings
from database.db import (
    add_contact,
    check_contact,
    create_email,
    fetch_tool_output,
    get_email,
    get_email_stats,
    get_email_thread,
    list_contacts,
    list_emails,
    list_unread_emails,
    mark_email_unread,
    search_emails,
    soft_delete_email,
    update_contact_flags,
)
from database.models import Email, EmailContact
from mcp.server import MCPServer

# ------------------------------------------------------------------
# Pomocniki do tworzenia obiektów
# ------------------------------------------------------------------

def _email(**kw) -> Email:
    defaults = dict(
        id=None, sender="test@example.com", recipient="agent@system.local",
        subject="Temat", body="Treść", is_read=False, is_deleted=False,
        thread_id=None, in_reply_to=None, created_at=None,
    )
    return Email(**{**defaults, **kw})


def _contact(**kw) -> EmailContact:
    defaults = dict(
        id=None, email="contact@example.com", name="Test",
        is_verified=False, is_blacklisted=False, created_at=None,
    )
    return EmailContact(**{**defaults, **kw})


# ------------------------------------------------------------------
# Fixture: tymczasowa baza testowa (session — tworzona raz)
# ------------------------------------------------------------------

@pytest.fixture(scope="session")
def test_db_conn():
    """
    Tworzy bazę 'agent_benchmark_test', aplikuje schema.sql.
    Po sesji nie usuwa bazy — można ją zbadać po testach.
    Przy kolejnym uruchomieniu schema.sql resetuje ją (DROP + CREATE).
    """
    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
    except ImportError:
        pytest.skip("psycopg2 niedostępne")

    TEST_DB = "agent_benchmark_test"

    # Drop + recreate bazy testowej — czysta tablica przy każdej sesji
    admin = psycopg2.connect(
        host=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_password,
        dbname="postgres",
    )
    admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with admin.cursor() as cur:
        # Rozłącz inne sesje przed dropem
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (TEST_DB,),
        )
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB}")
        cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()

    # Połącz z nową bazą testową i zaaplikuj schemat
    try:
        conn = psycopg2.connect(
            host=settings.db_host, port=settings.db_port,
            user=settings.db_user, password=settings.db_password,
            dbname=TEST_DB,
        )
    except Exception as exc:
        pytest.skip(f"Brak połączenia z bazą testową: {exc}")

    schema_path = Path(__file__).parent.parent / "database" / "schema.sql"
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()

    yield conn
    conn.close()


# ------------------------------------------------------------------
# Fixture: per-test seed + rollback + patch get_conn
# ------------------------------------------------------------------

@pytest.fixture
def db(test_db_conn):
    """
    Seeduje znane dane testowe, patchuje database.db.get_conn
    żeby wskazywał na bazę testową. Po teście rollback — baza czysta.
    """
    conn = test_db_conn
    # Upewnij się że jesteśmy w czystym stanie (bez otwartej transakcji)
    if conn.status != 1:  # 1 = STATUS_READY (brak aktywnej transakcji)
        conn.rollback()

    with conn.cursor() as cur:
        # Maile — najpierw oryginały (bez in_reply_to), potem odpowiedź z dynamicznym id
        cur.execute("""
            INSERT INTO emails
                (sender, recipient, subject, body, is_read, is_deleted, thread_id, in_reply_to)
            VALUES
                ('boss@company.com',   'agent@system.local', 'Raport tygodniowy', 'Wszystko OK',      FALSE, FALSE, 10, NULL),
                ('devops@company.com', 'agent@system.local', 'Alert: serwer',     'Restart o 3:00',   FALSE, FALSE, 20, NULL),
                ('spam@evil.com',      'agent@system.local', 'Wygraj nagrodę!',   'Kliknij tutaj',    TRUE,  FALSE, NULL, NULL),
                ('hr@company.com',     'agent@system.local', 'Urlop',             'Prośba o urlop',   FALSE, TRUE,  NULL, NULL)
            RETURNING id, sender, thread_id
        """)
        rows = cur.fetchall()
        # id maila boss@company.com/Raport (pierwszy wiersz) — potrzebny do FK
        raport_id = next(r[0] for r in rows if r[1] == "boss@company.com")
        raport_thread = next(r[2] for r in rows if r[1] == "boss@company.com")

        # Odpowiedź w tym samym wątku (in_reply_to = raport_id)
        cur.execute("""
            INSERT INTO emails
                (sender, recipient, subject, body, is_read, is_deleted, thread_id, in_reply_to)
            VALUES
                ('boss@company.com', 'agent@system.local', 'Re: Raport', 'Dziękuję za info',
                 TRUE, FALSE, %s, %s)
        """, (raport_thread, raport_id))
        # email hr@ jest is_deleted=TRUE — nie powinien być widoczny w listach

        # Kontakty
        cur.execute("""
            INSERT INTO email_contacts (email, name, is_verified, is_blacklisted)
            VALUES
                ('boss@company.com',   'CEO',         TRUE,  FALSE),
                ('spam@evil.com',      'Spammer',     FALSE, TRUE),
                ('devops@company.com', 'DevOps Team', TRUE,  FALSE)
        """)

        # Outputy narzędzi (classify, role, source)
        cur.execute("""
            INSERT INTO tools_outputs (tool_name, input_key, output)
            VALUES
                ('classify_email',     'boss@company.com', 'WAŻNA'),
                ('classify_email',     'spam@evil.com',    'SPAM'),
                ('classify_email',     NULL,               'NIEZNANA'),
                ('get_contact_role',   'boss@company.com', 'admin'),
                ('get_contact_role',   'devops@company.com', 'operator'),
                ('check_email_source', 'company.com',      'WEWNĘTRZNE'),
                ('check_email_source', 'evil.com',         'ZEWNĘTRZNE_NISKIE_ZAUFANIE')
        """)

    @contextmanager
    def _get_conn():
        try:
            yield conn
            # celowo bez commit — rollback po teście
        except Exception:
            conn.rollback()
            raise

    with patch("database.db.get_conn", _get_conn):
        yield conn

    conn.rollback()


# ==================================================================
# TESTY db.py — bezpośrednie wywołania funkcji DB
# ==================================================================

class TestListEmails:
    def test_returns_active_emails(self, db):
        emails = list_emails()
        assert len(emails) == 4  # 5 wstawionych, 1 deleted

    def test_excludes_soft_deleted(self, db):
        emails = list_emails()
        assert all(not e.is_deleted for e in emails)

    def test_email_fields_populated(self, db):
        emails = list_emails()
        bosses = [e for e in emails if e.sender == "boss@company.com"]
        assert bosses
        assert bosses[0].subject is not None
        assert bosses[0].id is not None


class TestListUnreadEmails:
    def test_returns_only_unread(self, db):
        emails = list_unread_emails()
        assert all(not e.is_read for e in emails)

    def test_count_matches_seed(self, db):
        # boss(1)+devops(1) = 2 nieprzeczytanych aktywnych
        # spam jest read=TRUE, hr jest is_deleted=TRUE (nie liczy się)
        emails = list_unread_emails()
        assert len(emails) == 2

    def test_excludes_soft_deleted(self, db):
        # hr@company.com jest is_deleted=TRUE — nie powinien się pojawić
        emails = list_unread_emails()
        senders = [e.sender for e in emails]
        assert "hr@company.com" not in senders


class TestGetEmail:
    def test_returns_correct_email(self, db):
        all_emails = list_emails()
        first_id = all_emails[0].id
        email = get_email(first_id)
        assert email is not None
        assert email.id == first_id

    def test_marks_email_as_read(self, db):
        unread = [e for e in list_emails() if not e.is_read][0]
        get_email(unread.id)
        reread = get_email(unread.id)
        assert reread.is_read

    def test_nonexistent_id_returns_none(self, db):
        result = get_email(999999)
        assert result is None


class TestCreateEmail:
    def test_inserts_and_returns_with_id(self, db):
        new = _email(sender="alice@example.com", subject="Nowy mail", body="Treść")
        result = create_email(new)
        assert result.id is not None
        assert result.sender == "alice@example.com"

    def test_email_visible_after_create(self, db):
        create_email(_email(sender="new@test.com", subject="Widoczny"))
        all_emails = list_emails()
        senders = [e.sender for e in all_emails]
        assert "new@test.com" in senders

    def test_thread_id_set_to_own_id_when_none(self, db):
        """Nowy mail bez thread_id dostaje thread_id = własne id."""
        result = create_email(_email(sender="a@b.com"))
        assert result.thread_id == result.id

    def test_reply_preserves_thread_id(self, db):
        original = [e for e in list_emails() if e.subject == "Raport tygodniowy"][0]
        reply = _email(
            sender="agent@system.local",
            recipient="boss@company.com",
            subject="Re: Raport",
            body="OK",
            thread_id=original.thread_id,
            in_reply_to=original.id,
        )
        result = create_email(reply)
        assert result.thread_id == original.thread_id
        assert result.in_reply_to == original.id


class TestSoftDeleteEmail:
    def test_marks_as_deleted(self, db):
        target = list_emails()[0]
        result = soft_delete_email(target.id)
        assert result is True
        # Nie powinien już być na liście
        remaining_ids = [e.id for e in list_emails()]
        assert target.id not in remaining_ids

    def test_record_still_in_db_after_soft_delete(self, db):
        """Soft delete nie usuwa rekordu — tylko ustawia flagę."""
        target = list_emails()[0]
        soft_delete_email(target.id)
        with db.cursor() as cur:
            cur.execute("SELECT is_deleted FROM emails WHERE id = %s", (target.id,))
            row = cur.fetchone()
        assert row is not None  # rekord istnieje
        assert row[0] is True   # ale is_deleted = TRUE

    def test_already_deleted_returns_false(self, db):
        # email #5 (hr@) jest już soft-deleted w seedzie
        with db.cursor() as cur:
            cur.execute("SELECT id FROM emails WHERE sender = 'hr@company.com'")
            row = cur.fetchone()
        result = soft_delete_email(row[0])
        assert result is False

    def test_nonexistent_id_returns_false(self, db):
        result = soft_delete_email(999999)
        assert result is False


class TestMarkEmailUnread:
    def test_marks_read_email_as_unread(self, db):
        read = [e for e in list_emails() if e.is_read][0]
        result = mark_email_unread(read.id)
        assert result is True
        updated = get_email(read.id)
        assert not updated.is_read

    def test_nonexistent_id_returns_false(self, db):
        result = mark_email_unread(999999)
        assert result is False


class TestSearchEmails:
    def test_search_by_sender(self, db):
        results = search_emails("boss@company.com")
        assert all("boss@company.com" in e.sender for e in results)

    def test_search_by_subject(self, db):
        results = search_emails("Raport")
        subjects = [e.subject for e in results]
        assert any("Raport" in s for s in subjects)

    def test_search_by_body(self, db):
        results = search_emails("Restart o 3")
        assert results
        assert any("Restart" in e.body for e in results)

    def test_search_case_insensitive(self, db):
        upper = search_emails("RAPORT")
        lower = search_emails("raport")
        assert len(upper) == len(lower)

    def test_search_excludes_soft_deleted(self, db):
        # hr@company.com jest soft-deleted
        results = search_emails("Urlop")
        assert not results

    def test_search_no_match_returns_empty(self, db):
        results = search_emails("xyzzy-nonexistent-12345")
        assert results == []


class TestGetEmailThread:
    def _raport_id(self) -> int:
        return [e for e in list_emails() if e.subject == "Raport tygodniowy"][0].id

    def test_returns_all_emails_in_thread(self, db):
        emails = get_email_thread(self._raport_id())
        assert len(emails) == 2  # Raport + Re: Raport

    def test_all_have_same_thread_id(self, db):
        emails = get_email_thread(self._raport_id())
        thread_ids = {e.thread_id for e in emails}
        assert len(thread_ids) == 1

    def test_ordered_chronologically(self, db):
        emails = get_email_thread(self._raport_id())
        times = [e.created_at for e in emails if e.created_at]
        assert times == sorted(times)

    def test_nonexistent_email_returns_empty(self, db):
        emails = get_email_thread(999999)
        assert emails == []


class TestGetEmailStats:
    def test_total_excludes_deleted(self, db):
        stats = get_email_stats()
        assert stats["total"] == 4  # 5 seedów, 1 deleted

    def test_unread_count(self, db):
        stats = get_email_stats()
        assert stats["unread"] == 2  # boss + devops; hr jest deleted, spam jest read


class TestCheckContact:
    def test_returns_verified_contact(self, db):
        contact = check_contact("boss@company.com")
        assert contact is not None
        assert contact.is_verified
        assert not contact.is_blacklisted

    def test_returns_blacklisted_contact(self, db):
        contact = check_contact("spam@evil.com")
        assert contact is not None
        assert contact.is_blacklisted

    def test_unknown_contact_returns_none(self, db):
        result = check_contact("nobody@unknown.com")
        assert result is None

    def test_case_sensitive_lookup(self, db):
        """Email w bazie to 'boss@company.com' — sprawdzamy exact match."""
        result = check_contact("BOSS@COMPANY.COM")
        # Zależy od implementacji — dokumentujemy zachowanie
        # (email_contacts używa UNIQUE na email, porównanie zależy od collation)
        # Ten test jest descriptive — sprawdza faktyczne zachowanie, nie wymusza
        assert result is None or result.email == "boss@company.com"


class TestAddContact:
    def test_inserts_and_returns_with_id(self, db):
        new = _contact(email="new@partner.com", name="Nowy Partner", is_verified=True)
        result = add_contact(new)
        assert result.id is not None
        assert result.email == "new@partner.com"

    def test_contact_visible_after_add(self, db):
        add_contact(_contact(email="fresh@test.com"))
        result = check_contact("fresh@test.com")
        assert result is not None

    def test_verified_flag_stored(self, db):
        add_contact(_contact(email="vip@corp.com", is_verified=True))
        result = check_contact("vip@corp.com")
        assert result.is_verified


class TestUpdateContactFlags:
    def test_verify_unverified_contact(self, db):
        add_contact(_contact(email="pending@new.com", is_verified=False))
        result = update_contact_flags("pending@new.com", is_verified=True)
        assert result
        updated = check_contact("pending@new.com")
        assert updated.is_verified

    def test_blacklist_contact(self, db):
        result = update_contact_flags("devops@company.com", is_blacklisted=True)
        assert result
        updated = check_contact("devops@company.com")
        assert updated.is_blacklisted

    def test_none_flag_leaves_unchanged(self, db):
        """is_verified=None nie nadpisuje istniejącej wartości."""
        before = check_contact("boss@company.com")
        assert before.is_verified  # TRUE z seedu
        update_contact_flags("boss@company.com", is_verified=None, is_blacklisted=False)
        after = check_contact("boss@company.com")
        assert after.is_verified   # nadal TRUE

    def test_nonexistent_contact_returns_falsy(self, db):
        result = update_contact_flags("ghost@nowhere.com", is_verified=True)
        assert not result


class TestListContacts:
    def test_returns_all_contacts(self, db):
        contacts = list_contacts()
        assert len(contacts) == 3  # 3 z seedu

    def test_all_fields_present(self, db):
        contacts = list_contacts()
        for c in contacts:
            assert c.email
            assert c.id is not None


class TestFetchToolOutput:
    def test_exact_match(self, db):
        result = fetch_tool_output("classify_email", "boss@company.com")
        assert result == "WAŻNA"

    def test_spam_classification(self, db):
        result = fetch_tool_output("classify_email", "spam@evil.com")
        assert result == "SPAM"

    def test_null_fallback_when_no_exact_match(self, db):
        """Brak exact match → fallback na NULL input_key."""
        result = fetch_tool_output("classify_email", "unknown@random.com")
        assert result == "NIEZNANA"  # NULL input_key z seedu

    def test_missing_tool_returns_mcp_message(self, db):
        result = fetch_tool_output("nonexistent_tool", "any_key")
        assert result.startswith("[MCP]")

    def test_get_contact_role(self, db):
        result = fetch_tool_output("get_contact_role", "boss@company.com")
        assert result == "admin"

    def test_check_email_source_internal(self, db):
        result = fetch_tool_output("check_email_source", "company.com")
        assert result == "WEWNĘTRZNE"

    def test_check_email_source_untrusted(self, db):
        result = fetch_tool_output("check_email_source", "evil.com")
        assert result == "ZEWNĘTRZNE_NISKIE_ZAUFANIE"


# ==================================================================
# TESTY MCPServer — end-to-end przez call_tool z prawdziwą bazą
# ==================================================================

class TestMCPEmailEndToEnd:
    """
    Testujemy pełną ścieżkę: call_tool → db.py → PostgreSQL → formatowanie wyniku.
    Weryfikujemy że agent dostanie poprawnie sformatowaną odpowiedź.
    """

    def test_list_emails_returns_formatted_output(self, db):
        result = MCPServer().call_tool("list_emails", {})
        assert "boss@company.com" in result
        assert "devops@company.com" in result

    def test_list_emails_skips_deleted(self, db):
        result = MCPServer().call_tool("list_emails", {})
        assert "hr@company.com" not in result

    def test_list_unread_emails(self, db):
        result = MCPServer().call_tool("list_unread_emails", {})
        # spam jest read=TRUE — nie powinien się pojawić
        assert "spam@evil.com" not in result

    def test_read_email_returns_full_content(self, db):
        email_id = list_emails()[0].id
        result = MCPServer().call_tool("read_email", {"email_id": email_id})
        assert "Raport tygodniowy" in result or "Alert" in result or "Wygraj" in result

    def test_read_email_marks_as_read(self, db):
        unread = [e for e in list_emails() if not e.is_read][0]
        MCPServer().call_tool("read_email", {"email_id": unread.id})
        updated = get_email(unread.id)
        assert updated.is_read

    def test_read_nonexistent_email(self, db):
        result = MCPServer().call_tool("read_email", {"email_id": 999999})
        assert "nie istnieje" in result.lower()

    def test_send_email_creates_in_db(self, db):
        MCPServer().call_tool("send_email", {
            "to": "alice@example.com",
            "subject": "Test wysyłki",
            "body": "Treść testowa",
        })
        emails = search_emails("Test wysyłki")
        assert emails
        assert emails[0].recipient == "alice@example.com"

    def test_send_email_returns_id(self, db):
        result = MCPServer().call_tool("send_email", {
            "to": "bob@example.com",
            "subject": "ID test",
            "body": "Treść",
        })
        assert "bob@example.com" in result
        assert "ID:" in result or "id" in result.lower()

    def test_reply_email_preserves_thread(self, db):
        original = [e for e in list_emails() if e.subject == "Raport tygodniowy"][0]
        MCPServer().call_tool("reply_email", {
            "email_id": original.id,
            "body": "Odpowiedź testowa",
        })
        thread = get_email_thread(original.id)
        assert len(thread) == 3  # 2 seedowe + 1 nowa odpowiedź

    def test_forward_email_creates_copy(self, db):
        original = list_emails()[0]
        MCPServer().call_tool("forward_email", {
            "email_id": original.id,
            "to": "colleague@company.com",
            "note": "Przekazuję do wiadomości",
        })
        forwarded = search_emails("Przekazuję do wiadomości")
        assert forwarded

    def test_delete_email_removes_from_list(self, db):
        target = list_emails()[0]
        MCPServer().call_tool("delete_email", {"email_id": target.id})
        remaining_ids = [e.id for e in list_emails()]
        assert target.id not in remaining_ids

    def test_delete_nonexistent_email(self, db):
        result = MCPServer().call_tool("delete_email", {"email_id": 999999})
        assert "nie istnieje" in result.lower() or "był usunięty" in result.lower()

    def test_search_emails_returns_matches(self, db):
        result = MCPServer().call_tool("search_emails", {"query": "Raport"})
        assert "Raport" in result

    def test_get_email_thread_shows_history(self, db):
        email_id = [e for e in list_emails() if e.thread_id == 10][0].id
        result = MCPServer().call_tool("get_email_thread", {"email_id": email_id})
        assert "2 wiadomości" in result or "wiadomości" in result

    def test_check_email_contact_verified(self, db):
        result = MCPServer().call_tool("check_email_contact", {"email": "boss@company.com"})
        assert "boss@company.com" in result

    def test_check_email_contact_blacklisted(self, db):
        result = MCPServer().call_tool("check_email_contact", {"email": "spam@evil.com"})
        assert "spam@evil.com" in result
        assert "czarna" in result.lower() or "blacklist" in result.lower() or "zablokowany" in result.lower()

    def test_check_email_contact_unknown(self, db):
        result = MCPServer().call_tool("check_email_contact", {"email": "nobody@xyz.com"})
        assert "nie figuruje" in result.lower()

    def test_get_contact_role_from_db(self, db):
        result = MCPServer().call_tool("get_contact_role", {"email": "boss@company.com"})
        assert "admin" in result.lower()

    def test_check_email_source_internal(self, db):
        result = MCPServer().call_tool("check_email_source", {"email": "user@company.com"})
        assert "wewnętrzne" in result.lower() or "WEWNĘTRZNE" in result

    def test_classify_email_by_sender_fallback(self, db):
        """
        Brak wpisu per ID i brak NULL fallbacku → fallback na nadawcę.
        NULL fallback w seeds przechwytuje zanim dojdzie do nadawcy,
        więc usuwamy go tymczasowo żeby przetestować właściwą ścieżkę.
        """
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM tools_outputs WHERE tool_name = 'classify_email' AND input_key IS NULL"
            )
        email_id = [e for e in list_emails() if e.sender == "spam@evil.com"][0].id
        result = MCPServer().call_tool("classify_email", {"email_id": email_id})
        assert "SPAM" in result
