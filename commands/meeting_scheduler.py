"""Handlery komend meeting-scheduler — prawdziwe operacje na tabeli meetings."""

from datetime import date

from database.db import cancel_meeting, create_meeting, list_meetings, list_meetings_today
from database.models import Meeting


def handle_list(args: dict[str, str]) -> str:
    meetings = list_meetings()
    if not meetings:
        return "=== Nadchodzące spotkania ===\nBrak zaplanowanych spotkań."
    return "=== Nadchodzące spotkania ===\n" + "\n".join(m.as_summary() for m in meetings)


def handle_today(args: dict[str, str]) -> str:
    meetings = list_meetings_today()
    today = date.today().strftime("%Y-%m-%d")
    if not meetings:
        return f"=== Spotkania na dziś ({today}) ===\nBrak spotkań na dziś."
    return f"=== Spotkania na dziś ({today}) ===\n" + "\n".join(m.as_summary() for m in meetings)


def handle_add(args: dict[str, str]) -> str:
    required = {"title", "date", "time"}
    missing = required - args.keys()
    if missing:
        flags = ", ".join(f"--{a}" for a in sorted(missing))
        return (
            f"[meeting-scheduler] Brak wymaganych argumentów: {flags}\n"
            f"Użycie: meeting-scheduler --add --title <tytuł> --date <YYYY-MM-DD> "
            f"--time <HH:MM> [--room <sala>] [--participants <uczestnicy>]"
        )
    try:
        meeting = create_meeting(Meeting(
            title=args["title"],
            meeting_date=args["date"],
            meeting_time=args["time"],
            room=args.get("room"),
            participants=args.get("participants"),
        ))
    except Exception as e:
        return f"[meeting-scheduler] Błąd podczas tworzenia spotkania: {e}"

    return (
        f"[meeting-scheduler] Spotkanie zaplanowane pomyślnie.\n"
        f"───────────────────────────────────────────\n"
        f"Tytuł:       {meeting.title}\n"
        f"Data:        {meeting.meeting_date.strftime('%Y-%m-%d')}\n"
        f"Godzina:     {meeting.meeting_time.strftime('%H:%M')}\n"
        f"Sala:        {meeting.room or '—'}\n"
        f"Uczestnicy:  {meeting.participants or '—'}\n"
        f"───────────────────────────────────────────\n"
        f"ID spotkania: {meeting.id}\n"
        f"Status: OK"
    )


def handle_cancel(args: dict[str, str]) -> str:
    if "id" not in args:
        return (
            "[meeting-scheduler] Brak wymaganego argumentu --id\n"
            "Użycie: meeting-scheduler --cancel --id <ID>"
        )
    try:
        meeting_id = int(args["id"])
    except ValueError:
        return f"[meeting-scheduler] --id musi być liczbą całkowitą, otrzymano: '{args['id']}'"

    if not cancel_meeting(meeting_id):
        return f"[meeting-scheduler] Spotkanie o ID {meeting_id} nie istnieje lub jest już anulowane."
    return (
        f"[meeting-scheduler] Spotkanie ID {meeting_id} zostało anulowane.\n"
        f"Uczestnicy zostaną powiadomieni automatycznie."
    )


HANDLERS: dict[str, callable] = {
    "meeting-scheduler --list":   handle_list,
    "meeting-scheduler --today":  handle_today,
    "meeting-scheduler --add":    handle_add,
    "meeting-scheduler --cancel": handle_cancel,
}
