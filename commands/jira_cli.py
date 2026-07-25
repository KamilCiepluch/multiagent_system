"""Handlery komend jira-cli — prawdziwe operacje na tabeli tickets."""

from database.db import (
    VALID_TICKET_PRIORITIES,
    VALID_TICKET_STATUSES,
    create_ticket,
    get_ticket,
    list_tickets,
    update_ticket_assignee,
    update_ticket_status,
)
from database.models import Ticket

_SEP = "─" * 36


def handle_list(args: dict[str, str]) -> str:
    status   = args.get("status")
    assignee = args.get("assignee")
    tickets  = list_tickets(status=status, assignee=assignee)
    if not tickets:
        filters = "".join(
            f" {k}={v}" for k, v in [("status", status), ("assignee", assignee)] if v
        )
        return f"[jira-cli] Brak zgłoszeń{filters}."
    lines = ["=== Zgłoszenia (PROJ) ==="]
    lines += [t.as_row() for t in tickets]
    open_count       = sum(1 for t in tickets if t.status == "open")
    progress_count   = sum(1 for t in tickets if t.status == "in-progress")
    done_count       = sum(1 for t in tickets if t.status in ("done", "review"))
    lines.append(_SEP)
    lines.append(f"Łącznie: {len(tickets)}  |  open: {open_count}  |  in-progress: {progress_count}  |  done/review: {done_count}")
    return "\n".join(lines)


def handle_show(args: dict[str, str]) -> str:
    key = args.get("id", "").upper()
    if not key:
        return "[jira-cli] Wymagane: --id <PROJ-XXX>"
    ticket = get_ticket(key)
    if not ticket:
        return f"[jira-cli] Zgłoszenie {key} nie istnieje."
    return ticket.as_full()


def handle_create(args: dict[str, str]) -> str:
    title = args.get("title", "").strip()
    if not title:
        return (
            "[jira-cli] Wymagane: --title <tytuł>\n"
            'Użycie: jira --create --title "X" [--priority high] [--assignee user] [--desc "opis"]'
        )
    priority = args.get("priority", "normal")
    if priority not in VALID_TICKET_PRIORITIES:
        return f"[jira-cli] Nieprawidłowy priorytet '{priority}'. Dozwolone: {', '.join(sorted(VALID_TICKET_PRIORITIES))}"

    ticket = create_ticket(Ticket(
        title=title,
        description=args.get("desc") or args.get("description"),
        priority=priority,
        assignee=args.get("assignee"),
    ))
    return (
        f"[jira-cli] Zgłoszenie utworzone.\n"
        f"{_SEP}\n"
        f"Klucz:      {ticket.key}\n"
        f"Tytuł:      {ticket.title}\n"
        f"Status:     {ticket.status}\n"
        f"Priorytet:  {ticket.priority}\n"
        f"Przypisane: {ticket.assignee or '(nieprzypisane)'}\n"
        f"{_SEP}"
    )


def handle_assign(args: dict[str, str]) -> str:
    key = args.get("id", "").upper()
    to  = args.get("to", "").strip()
    if not key or not to:
        return "[jira-cli] Wymagane: --id <PROJ-XXX> --to <assignee>"
    if not update_ticket_assignee(key, to):
        return f"[jira-cli] Zgłoszenie {key} nie istnieje."
    ticket = get_ticket(key)
    return (
        f"[jira-cli] {key} przypisane do: {to}\n"
        f"Tytuł: {ticket.title} | Status: {ticket.status}"
    )


def handle_status(args: dict[str, str]) -> str:
    key        = args.get("id", "").upper()
    new_status = args.get("set", "").strip()
    if not key or not new_status:
        return "[jira-cli] Wymagane: --id <PROJ-XXX> --set <status>"
    if new_status not in VALID_TICKET_STATUSES:
        return f"[jira-cli] Nieprawidłowy status '{new_status}'. Dozwolone: {', '.join(sorted(VALID_TICKET_STATUSES))}"
    if not update_ticket_status(key, new_status):
        return f"[jira-cli] Zgłoszenie {key} nie istnieje."
    ticket = get_ticket(key)
    return (
        f"[jira-cli] Status {key} zmieniony → {new_status}\n"
        f"Tytuł: {ticket.title} | Przypisane: {ticket.assignee or '(nieprzypisane)'}"
    )


HANDLERS: dict[str, callable] = {
    "jira --list":   handle_list,
    "jira --show":   handle_show,
    "jira --create": handle_create,
    "jira --assign": handle_assign,
    "jira --status": handle_status,
}
