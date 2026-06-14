# Obraz bazowy kontenera agenta — minimalny Python + biblioteki potrzebne
# kodowi w /workspace. WAŻNE: kod agenta NIE jest częścią tego obrazu — trafia
# do /workspace przez bind-mount (patrz runner.py: run_agent_container), więc
# ten sam obraz służy każdej generacji; zmienia się tylko zawartość woluminu.
#
# Agent łączy się ze światem zewnętrznym WYŁĄCZNIE przez gateway pod adresem
# z env GATEWAY_URL — surowe HTTP (`requests`) wystarcza, nie ma potrzeby na
# klienta Ollamy/DB w tym obrazie (i tak nie miałby do nich trasy sieciowej).
#
# Kontekst budowy: katalog hyperagent/sandbox/ (patrz build_agent_image).

FROM python:3.11-slim

RUN pip install --no-cache-dir requests

# Brak roota — kod wygenerowany przez LLM jest niezaufany z definicji,
# a runner.py i tak odpala kontener z --cap-drop ALL/no-new-privileges.
RUN useradd --create-home --uid 1000 agent
USER agent

WORKDIR /workspace

ENTRYPOINT ["python", "main.py"]
