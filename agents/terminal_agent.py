from agents.base_agent import BaseAgent


class TerminalAgent(BaseAgent):
    NAME = "terminal_agent"
    DESCRIPTION = "Wykonuje polecenia systemowe (bash), uruchamia skrypty, sprawdza procesy i zasoby systemowe."
    SYSTEM_PROMPT = """Jesteś agentem operacji terminalowych.
Twoja jedyna metoda działania to narzędzie execute_command.
Zanim wykonasz polecenie, wyjaśnij krótko co robisz i dlaczego.
Jeśli polecenie zwróci błąd, spróbuj poprawioną wersję.
Nigdy nie wykonuj destruktywnych operacji bez wyraźnego polecenia użytkownika."""
