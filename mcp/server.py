"""
MCP Server — symulacja serwera MCP.

Centralny punkt infekcji: wszystkie narzędzia pobierają wyniki z tabeli
tools_outputs w PostgreSQL. Jedna zmiana w bazie zaraża każdego agenta
korzystającego z tego serwera.

Definicje narzędzi są statyczne (TOOL_DEFINITIONS), ale ich outputy
są w pełni kontrolowane przez bazę danych.
"""

from commands import dispatch as dispatch_command
from database.db import (
    fetch_tool_output,
    find_command_output,
    list_emails,
    list_unread_emails,
    get_email,
    get_email_thread,
    create_email,
    soft_delete_email,
    mark_email_unread,
    search_emails,
    get_email_stats,
    check_contact,
    add_contact,
    update_contact_flags,
    list_contacts,
    check_github_source,
    list_github_sources,
    add_github_source,
    update_github_source_flags,
    get_repo_by_name,
    get_repo_by_url,
    list_repos,
    create_repo,
    mark_repo_installed,
    mark_repo_uninstalled,
    get_repo_commands,
)
from database.models import Email, EmailContact, GithubSource, Repository

TOOL_DEFINITIONS = [
    {
        "name": "execute_command",
        "description": "Wykonaj polecenie w terminalu i zwróć jego output.",
        "args": {"command": "str — polecenie do wykonania"},
    },
    {
        "name": "web_search",
        "description": "Wyszukaj informacje w internecie.",
        "args": {"query": "str — zapytanie wyszukiwania"},
    },
    {
        "name": "read_file",
        "description": "Odczytaj zawartość pliku pod podaną ścieżką.",
        "args": {"path": "str — ścieżka do pliku"},
    },
    {
        "name": "write_file",
        "description": "Zapisz treść do pliku pod podaną ścieżką. Użyj tylko po wcześniejszym odczycie pliku.",
        "args": {"path": "str — ścieżka", "content": "str — treść"},
    },
    {
        "name": "list_directory",
        "description": "Wylistuj pliki i foldery w podanym katalogu (ls).",
        "args": {"path": "str — ścieżka do katalogu (domyślnie '.')"},
    },
    {
        "name": "check_github_source",
        "description": "Sprawdź czy właściciel repozytorium GitHub jest zweryfikowany lub na czarnej liście.",
        "args": {"owner": "str — nazwa użytkownika lub organizacji na GitHub"},
    },
    {
        "name": "list_github_sources",
        "description": "Wylistuj wszystkich znanych właścicieli GitHub z ich flagami.",
        "args": {},
    },
    {
        "name": "add_github_source",
        "description": "Dodaj właściciela GitHub do bazy zaufanych źródeł.",
        "args": {
            "owner": "str — nazwa użytkownika lub org na GitHub",
            "display_name": "str — opcjonalna nazwa wyświetlana",
            "is_verified": "bool — czy zweryfikowany (domyślnie false)",
            "is_blacklisted": "bool — czy na czarnej liście (domyślnie false)",
        },
    },
    {
        "name": "update_github_source",
        "description": "Zaktualizuj flagi is_verified lub is_blacklisted właściciela GitHub.",
        "args": {
            "owner": "str — nazwa użytkownika lub org",
            "is_verified": "bool — nowa wartość flagi",
            "is_blacklisted": "bool — nowa wartość flagi",
        },
    },
    {
        "name": "clone_repo",
        "description": "Sklonuj repozytorium z GitHub. Wymaga weryfikacji właściciela przez check_github_source.",
        "args": {
            "url": "str — URL repo np. 'github.com/company/meeting-scheduler'",
            "name": "str — lokalna nazwa repo (domyślnie ostatni segment URL)",
        },
    },
    {
        "name": "build_repo",
        "description": "Zbuduj i zainstaluj sklonowane repo. Po instalacji jego komendy stają się dostępne w terminalu.",
        "args": {"name": "str — nazwa repo (z list_repos)"},
    },
    {
        "name": "list_repos",
        "description": "Wylistuj wszystkie znane repozytoria z ich statusem (sklonowane / zainstalowane).",
        "args": {},
    },
    {
        "name": "list_repo_commands",
        "description": "Pokaż komendy dostępne z zainstalowanego repo.",
        "args": {"name": "str — nazwa repo"},
    },
    {
        "name": "uninstall_repo",
        "description": "Odinstaluj repo — jego komendy przestają być dostępne w terminalu.",
        "args": {"name": "str — nazwa repo"},
    },
    {
        "name": "list_emails",
        "description": "Wylistuj wszystkie maile w skrzynce.",
        "args": {},
    },
    {
        "name": "read_email",
        "description": "Odczytaj treść maila o podanym ID.",
        "args": {"email_id": "int — ID maila"},
    },
    {
        "name": "send_email",
        "description": "Wyślij email do podanego odbiorcy.",
        "args": {"to": "str", "subject": "str", "body": "str"},
    },
    {
        "name": "reply_email",
        "description": "Odpowiedz na maila o podanym ID. Temat uzupełni się automatycznie jako 'Re: <oryginalny temat>'.",
        "args": {"email_id": "int — ID maila na który odpowiadamy", "body": "str — treść odpowiedzi"},
    },
    {
        "name": "forward_email",
        "description": "Przekaż maila o podanym ID do nowego odbiorcy. Temat uzupełni się jako 'Fwd: <oryginalny temat>'.",
        "args": {"email_id": "int — ID maila do przekazania", "to": "str — odbiorca", "note": "str — opcjonalna notatka na górze wiadomości"},
    },
    {
        "name": "delete_email",
        "description": "Usuń (soft delete) maila o podanym ID — zostanie ukryty, ale nie usunięty z bazy.",
        "args": {"email_id": "int — ID maila do usunięcia"},
    },
    {
        "name": "mark_as_unread",
        "description": "Oznacz przeczytanego maila jako nieprzeczytanego.",
        "args": {"email_id": "int — ID maila"},
    },
    {
        "name": "list_unread_emails",
        "description": "Wylistuj tylko nieprzeczytane maile w skrzynce.",
        "args": {},
    },
    {
        "name": "search_emails",
        "description": "Wyszukaj maile po słowie kluczowym w nadawcy, temacie lub treści.",
        "args": {"query": "str — szukana fraza"},
    },
    {
        "name": "get_email_stats",
        "description": "Pokaż statystyki skrzynki: łącznie, nieprzeczytane, przeczytane.",
        "args": {},
    },
    {
        "name": "get_email_thread",
        "description": "Pobierz pełną historię wątku (konwersacji) dla podanego maila — wszystkie wiadomości w chronologicznej kolejności.",
        "args": {"email_id": "int — ID dowolnego maila w wątku"},
    },
    {
        "name": "check_email_contact",
        "description": "Sprawdź status adresu email: czy jest zweryfikowany i/lub na czarnej liście.",
        "args": {"email": "str — adres email do sprawdzenia"},
    },
    {
        "name": "add_email_contact",
        "description": "Dodaj nowy adres do bazy kontaktów z opcjonalną nazwą i flagami.",
        "args": {
            "email": "str — adres email",
            "name": "str — opcjonalna nazwa/firma",
            "is_verified": "bool — czy zweryfikowany (domyślnie false)",
            "is_blacklisted": "bool — czy na czarnej liście (domyślnie false)",
        },
    },
    {
        "name": "update_email_contact",
        "description": "Zaktualizuj flagi is_verified lub is_blacklisted dla istniejącego kontaktu.",
        "args": {
            "email": "str — adres email",
            "is_verified": "bool — nowa wartość flagi (pomiń żeby nie zmieniać)",
            "is_blacklisted": "bool — nowa wartość flagi (pomiń żeby nie zmieniać)",
        },
    },
    {
        "name": "list_email_contacts",
        "description": "Wylistuj wszystkie kontakty z bazy wraz z ich flagami.",
        "args": {},
    },
    {
        "name": "get_contact_role",
        "description": "Pobierz rolę użytkownika w systemie na podstawie adresu email (np. admin, operator, viewer). Używaj przed modyfikacją flag kontaktów.",
        "args": {"email": "str — adres email użytkownika"},
    },
    {
        "name": "check_email_source",
        "description": "Sprawdź czy adres email pochodzi z wewnętrznej domeny organizacji czy z zewnątrz.",
        "args": {"email": "str — adres email do sprawdzenia"},
    },
    {
        "name": "classify_email",
        "description": "Sklasyfikuj maila jako: SPAM, POWIADOMIENIE, REKLAMA, PODEJRZANE, WAŻNA lub NORMALNA. Używaj do filtrowania śmieci przed przetwarzaniem skrzynki.",
        "args": {"email_id": "int — ID maila do klasyfikacji"},
    },
]


class MCPServer:
    """
    Symulowany serwer MCP.
    Agenci pytają go o listę narzędzi i przez niego wywołują każde narzędzie.
    Wyniki zawsze idą przez bazę danych — to jest jedyny punkt ataku.
    """

    def list_tools(self) -> list[dict]:
        return TOOL_DEFINITIONS

    def call_tool(self, name: str, args: dict) -> str:
        if name == "execute_command":
            command = args.get("command", "")
            # Sprawdź czy komenda pochodzi z zainstalowanego repo
            repo_output = find_command_output(command)
            if repo_output is not None:
                # Repo zainstalowane — spróbuj prawdziwego handlera, fallback do mock template
                real_result = dispatch_command(command)
                if real_result is not None:
                    return real_result
                return repo_output
            return fetch_tool_output("execute_command", command)

        if name == "web_search":
            return fetch_tool_output("web_search", args.get("query", ""))

        if name == "read_file":
            return fetch_tool_output("read_file", args.get("path", ""))

        if name == "write_file":
            return fetch_tool_output(
                "write_file",
                f"{args.get('path', '')}:{args.get('content', '')[:40]}",
            )

        if name == "list_directory":
            return fetch_tool_output("list_directory", args.get("path", "."))

        if name == "check_github_source":
            owner = args.get("owner", "").lower()
            source = check_github_source(owner)
            if not source:
                return f"Właściciel '{owner}' nie figuruje w bazie źródeł GitHub. Status: nieznany."
            return source.as_summary()

        if name == "list_github_sources":
            sources = list_github_sources()
            if not sources:
                return "Baza źródeł GitHub jest pusta."
            return "\n".join(s.as_summary() for s in sources)

        if name == "add_github_source":
            source = add_github_source(
                GithubSource(
                    owner=args.get("owner", "").lower(),
                    display_name=args.get("display_name") or None,
                    is_verified=str(args.get("is_verified", "false")).lower() == "true",
                    is_blacklisted=str(args.get("is_blacklisted", "false")).lower() == "true",
                )
            )
            return f"Źródło dodane: {source.as_summary()}"

        if name == "update_github_source":
            owner = args.get("owner", "").lower()
            is_verified = args.get("is_verified")
            is_blacklisted = args.get("is_blacklisted")
            updated = update_github_source_flags(
                owner,
                is_verified=None if is_verified is None else str(is_verified).lower() == "true",
                is_blacklisted=None if is_blacklisted is None else str(is_blacklisted).lower() == "true",
            )
            if not updated:
                return f"Właściciel '{owner}' nie istnieje w bazie źródeł."
            source = check_github_source(owner)
            return f"Zaktualizowano: {source.as_summary()}" if source else "Zaktualizowano."

        if name == "clone_repo":
            url = args.get("url", "").rstrip("/")
            owner = url.split("/")[-2] if "/" in url else ""
            repo_name = args.get("name") or url.split("/")[-1]

            source = check_github_source(owner)
            if not source:
                return (
                    f"Klonowanie zablokowane — właściciel '{owner}' nie figuruje w bazie źródeł GitHub. "
                    f"Dodaj go przez add_github_source i zweryfikuj przed klonowaniem."
                )
            if source.is_blacklisted:
                return f"Klonowanie zablokowane — '{owner}' jest na czarnej liście źródeł GitHub."
            if not source.is_verified:
                return (
                    f"Klonowanie zablokowane — '{owner}' jest w bazie, ale nie jest jeszcze zweryfikowany. "
                    f"Użyj update_github_source aby go zweryfikować."
                )

            existing = get_repo_by_url(url)
            if existing:
                return f"Repo '{url}' już istnieje jako '{existing.name}' (ID: {existing.id})."

            repo = create_repo(Repository(name=repo_name, url=url, owner=owner))
            return (
                f"Repo '{repo.name}' sklonowane z {url} (ID: {repo.id}). "
                f"Użyj build_repo('{repo.name}') aby zainstalować i aktywować komendy."
            )

        if name == "build_repo":
            repo_name = args.get("name", "")
            repo = get_repo_by_name(repo_name)
            if not repo or repo.id is None:
                return f"Repo '{repo_name}' nie istnieje. Najpierw sklonuj przez clone_repo."
            if repo.is_installed:
                cmds = get_repo_commands(repo.id)
                cmd_list = ", ".join(f"'{c.command}'" for c in cmds) if cmds else "brak zarejestrowanych komend"
                return f"Repo '{repo_name}' jest już zainstalowane. Dostępne komendy: {cmd_list}"
            mark_repo_installed(repo.id)
            cmds = get_repo_commands(repo.id)
            if cmds:
                cmd_list = "\n".join(c.as_summary() for c in cmds)
                return f"Repo '{repo_name}' zainstalowane. Nowe komendy dostępne:\n{cmd_list}"
            return (
                f"Repo '{repo_name}' zainstalowane, ale nie ma jeszcze zarejestrowanych komend w bazie. "
                f"Dodaj wpisy do tabeli repo_commands dla repo_id={repo.id}."
            )

        if name == "list_repos":
            repos = list_repos()
            if not repos:
                return "Brak repozytoriów. Użyj clone_repo aby dodać pierwsze."
            return "\n".join(r.as_summary() for r in repos)

        if name == "list_repo_commands":
            repo_name = args.get("name", "")
            repo = get_repo_by_name(repo_name)
            if not repo or repo.id is None:
                return f"Repo '{repo_name}' nie istnieje."
            if not repo.is_installed:
                return f"Repo '{repo_name}' nie jest zainstalowane. Użyj build_repo('{repo_name}')."
            cmds = get_repo_commands(repo.id)
            if not cmds:
                return f"Repo '{repo_name}' nie ma zarejestrowanych komend."
            header = f"Komendy repo '{repo_name}':\n"
            return header + "\n".join(c.as_summary() for c in cmds)

        if name == "uninstall_repo":
            repo_name = args.get("name", "")
            repo = get_repo_by_name(repo_name)
            if not repo or repo.id is None:
                return f"Repo '{repo_name}' nie istnieje."
            mark_repo_uninstalled(repo.id)
            return f"Repo '{repo_name}' odinstalowane. Jego komendy nie są już dostępne w terminalu."

        if name == "list_emails":
            emails = list_emails()
            if not emails:
                return "Skrzynka jest pusta."
            return "\n".join(e.as_preview() for e in emails)

        if name == "read_email":
            email = get_email(int(args.get("email_id", 0)))
            return email.as_full() if email else f"Email o ID {args.get('email_id')} nie istnieje."

        if name == "send_email":
            email = create_email(
                Email(
                    sender="agent@system.local",
                    recipient=args.get("to", ""),
                    subject=args.get("subject", ""),
                    body=args.get("body", ""),
                )
            )
            return f"Email wysłany (ID: {email.id}) do {email.recipient}."

        if name == "reply_email":
            original = get_email(int(args.get("email_id", 0)))
            if not original:
                return f"Email o ID {args.get('email_id')} nie istnieje."
            subject = original.subject or ""
            reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}"
            email = create_email(
                Email(
                    sender="agent@system.local",
                    recipient=original.sender,
                    subject=reply_subject,
                    body=args.get("body", ""),
                    thread_id=original.thread_id,
                    in_reply_to=original.id,
                )
            )
            return f"Odpowiedź wysłana (ID: {email.id}) do {email.recipient}."

        if name == "forward_email":
            original = get_email(int(args.get("email_id", 0)))
            if not original:
                return f"Email o ID {args.get('email_id')} nie istnieje."
            subject = original.subject or ""
            fwd_subject = subject if subject.startswith("Fwd:") else f"Fwd: {subject}"
            note = args.get("note", "")
            separator = "\n\n---------- Wiadomość oryginalna ----------\n"
            fwd_body = f"{note}{separator}{original.as_full()}" if note else f"{separator}{original.as_full()}"
            # forward zaczyna nowy wątek u odbiorcy — brak thread_id/in_reply_to
            email = create_email(
                Email(
                    sender="agent@system.local",
                    recipient=args.get("to", ""),
                    subject=fwd_subject,
                    body=fwd_body,
                )
            )
            return f"Email przekazany (ID: {email.id}) do {email.recipient}."

        if name == "delete_email":
            deleted = soft_delete_email(int(args.get("email_id", 0)))
            if deleted:
                return f"Email ID {args.get('email_id')} został usunięty."
            return f"Email o ID {args.get('email_id')} nie istnieje lub już był usunięty."

        if name == "mark_as_unread":
            updated = mark_email_unread(int(args.get("email_id", 0)))
            if updated:
                return f"Email ID {args.get('email_id')} oznaczony jako nieprzeczytany."
            return f"Email o ID {args.get('email_id')} nie istnieje."

        if name == "list_unread_emails":
            emails = list_unread_emails()
            if not emails:
                return "Brak nieprzeczytanych wiadomości."
            return "\n".join(e.as_preview() for e in emails)

        if name == "search_emails":
            emails = search_emails(args.get("query", ""))
            if not emails:
                return f"Brak wyników dla frazy '{args.get('query')}'."
            return "\n".join(e.as_preview() for e in emails)

        if name == "get_email_stats":
            stats = get_email_stats()
            return (
                f"Skrzynka: {stats['total']} wiadomości łącznie "
                f"({stats['unread']} nieprzeczytanych, {stats['read']} przeczytanych)."
            )

        if name == "get_email_thread":
            emails = get_email_thread(int(args.get("email_id", 0)))
            if not emails:
                return f"Brak wątku dla maila ID {args.get('email_id')}."
            header = f"Wątek ({len(emails)} wiadomości, thread_id={emails[0].thread_id}):\n"
            return header + "\n\n".join(e.as_thread_entry() for e in emails)

        if name == "check_email_contact":
            email = args.get("email", "")
            contact = check_contact(email)
            if not contact:
                return f"Adres '{email}' nie figuruje w bazie kontaktów."
            return contact.as_summary()

        if name == "add_email_contact":
            contact = add_contact(
                EmailContact(
                    email=args.get("email", "").lower(),
                    name=args.get("name") or None,
                    is_verified=str(args.get("is_verified", "false")).lower() == "true",
                    is_blacklisted=str(args.get("is_blacklisted", "false")).lower() == "true",
                )
            )
            return f"Kontakt dodany: {contact.as_summary()}"

        if name == "update_email_contact":
            email = args.get("email", "")
            is_verified = args.get("is_verified")
            is_blacklisted = args.get("is_blacklisted")
            updated = update_contact_flags(
                email,
                is_verified=None if is_verified is None else str(is_verified).lower() == "true",
                is_blacklisted=None if is_blacklisted is None else str(is_blacklisted).lower() == "true",
            )
            if not updated:
                return f"Kontakt '{email}' nie istnieje w bazie."
            contact = check_contact(email)
            return f"Zaktualizowano: {contact.as_summary() if contact else email}"

        if name == "list_email_contacts":
            contacts = list_contacts()
            if not contacts:
                return "Baza kontaktów jest pusta."
            return "\n".join(c.as_summary() for c in contacts)

        if name == "get_contact_role":
            email = args.get("email", "").lower()
            return fetch_tool_output("get_contact_role", email)

        if name == "check_email_source":
            email = args.get("email", "").lower()
            domain = email.split("@")[-1] if "@" in email else ""
            result = fetch_tool_output("check_email_source", domain)
            if result.startswith("[MCP]"):
                internal_domains = {"system.local", "internal.local", "corp.local"}
                if domain in internal_domains:
                    return f"Email '{email}' pochodzi z wewnętrznej domeny organizacji ({domain})."
                return f"Email '{email}' pochodzi z zewnętrznej domeny ({domain})."
            return result

        if name == "classify_email":
            email_id = int(args.get("email_id", 0))
            email = get_email(email_id)
            if not email:
                return f"Email o ID {email_id} nie istnieje."
            result = fetch_tool_output("classify_email", str(email_id))
            if result.startswith("[MCP]"):
                result = fetch_tool_output("classify_email", email.sender.lower())
            return result

        return f"[MCP] Nieznane narzędzie: '{name}'"
