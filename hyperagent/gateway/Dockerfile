# Obraz gatewaya — JEDYNY proces, przez który hyperagent dotyka świata
# zewnętrznego (patrz gateway/server.py: _call_logged). W przeciwieństwie do
# obrazu agenta (sandbox/Dockerfile), TEN kod JEST "wypieczony" w obrazie —
# żyje poza katalogiem, do którego agent ma dostęp zapisu (cała architektura
# "niełamliwego logowania" stoi na tym, że agent fizycznie nie może go
# zmienić ani ominąć).
#
# Gateway importuje cały system docelowy (config, database, graph, agents,
# attack_core, payload_attack, hyperagent) — stąd kontekst budowy to KORZEŃ repo,
# nie ten katalog:
#   docker build -t hyperagent-gateway:latest -f hyperagent/gateway/Dockerfile .
# (albo: docker-compose -f docker-compose.yml -f docker-compose.hyperagent.yml build gateway)

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "hyperagent.gateway.server"]
