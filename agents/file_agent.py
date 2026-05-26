from agents.base_agent import BaseAgent


class FileAgent(BaseAgent):
    NAME = "file_agent"
    DESCRIPTION = "Odczytuje i zapisuje pliki na dysku. Używaj gdy zadanie wymaga dostępu do zawartości pliku lub zapisu danych."
    SYSTEM_PROMPT = """Jesteś agentem operacji na plikach.
Masz dostęp do narzędzi read_file i write_file.
Gdy dostajesz zadanie:
- Odczytuj pliki przez read_file podając dokładną ścieżkę.
- Zapisuj pliki przez write_file — zawsze potwierdź co zapisujesz.
- Nigdy nie nadpisuj pliku bez wcześniejszego odczytu i potwierdzenia.
Raportuj zawartość pliku w czytelnym formacie."""
