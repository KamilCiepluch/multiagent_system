"""
Sandbox runner — cykl życia kontenerów agenta I gatewaya przez Docker CLI
(`subprocess`, bez nowej zależności w stylu SDK `docker-py` — binarka `docker`
już jest). Oba dzielą tę samą plumbingę (`_docker`/`_force_stop`), więc żyją
w jednym module — host (`hyperagent.loop`) odpala FRESH gateway, potem agenta,
i sprząta po obu po zakończeniu rundy.

WAŻNE: ten moduł NIE JEST mechanizmem izolacji — jest tylko jego operatorem.
Samą izolację gwarantują parametry, z którymi kontener jest odpalany (a te są
egzekwowane przez silnik Dockera, nie przez nasz kod):

  • `--network <hyperagent_net>` — sieć Docker `internal: true`
    (`docker-compose.hyperagent.yml`): kontener na niej fizycznie NIE MA
    trasy routingu do hosta, Postgresa, Ollamy ani internetu. Jedyny inny
    kontener na tej sieci to gateway (`hyperagent/gateway`) — czyli jedyne,
    z czym agent w ogóle może "porozmawiać"
  • `--memory` / `--cpus` / `--pids-limit`, `--cap-drop ALL`,
    `--security-opt no-new-privileges`, BRAK `--privileged` — kod
    wygenerowany przez LLM jest z definicji niezaufany
  • twardy timeout (subprocess `timeout=` + `docker kill`/`rm -f`) —
    zawieszony/zapętlony agent dostaje SIGKILL po przekroczeniu limitu

`/workspace` (bind-mount z `workspace_dir`, read-write) to JEDYNA rzecz, którą
agent może czytać/pisać/uruchamiać — łącznie z własnym kodem orkiestracji.
Granica "czy agent może wyjść poza nią" jest egzekwowana przez sam kontener
(wolumin to jedyny zapisywalny katalog poza efemerycznym systemem plików
obrazu), więc nie potrzeba dodatkowej kontroli na poziomie aplikacji.
"""

from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from config import settings

_SANDBOX_DIR = Path(__file__).parent
_REPO_ROOT = _SANDBOX_DIR.parent.parent
_DEFAULT_IMAGE = "hyperagent-agent:latest"
_DEFAULT_NETWORK = "hyperagent_net"

_DEFAULT_GATEWAY_IMAGE = "hyperagent-gateway:latest"
_GATEWAY_DOCKERFILE = _REPO_ROOT / "hyperagent" / "gateway" / "Dockerfile"
_GATEWAY_PORT = 8800
# Nazwa domyślnej sieci `docker-compose.yml` (tej, do której podłączony jest
# `postgres`) — Compose nazywa ją `<nazwa_projektu>_default`, a nazwa projektu
# to (bez jawnego `name:` w pliku) nazwa katalogu repo. Jeśli host uruchamia
# stack pod inną nazwą projektu, trzeba podać `db_network=` jawnie — patrz
# `launch_gateway`.
_DEFAULT_DB_NETWORK = "agents_blocks_default"
# Nazwa usługi `postgres` w `docker-compose.yml` — to ten alias DNS Compose
# wystawia na `_DEFAULT_DB_NETWORK` (obok nazwy kontenera). Wewnątrz gatewaya
# `settings.db_host` MUSI wskazywać na to (nie na domyślne `localhost` z
# `config.py` — wewnątrz kontenera `localhost` to sam kontener gatewaya).
_DEFAULT_DB_HOST = "postgres"


def _gateway_ollama_base_url() -> str:
    """`settings.ollama_base_url` (domyślnie `http://localhost:11434`) wskazuje
    na Ollamę NA HOŚCIE — wewnątrz kontenera gatewaya `localhost` to sam
    kontener. `--add-host host.docker.internal:host-gateway` (patrz
    `launch_gateway`) daje jedyną trasę do hosta, więc podmieniamy host w
    URL-u, zachowując port skonfigurowany przez użytkownika."""
    parsed = urlparse(settings.ollama_base_url)
    return f"{parsed.scheme}://host.docker.internal:{parsed.port or 11434}"


@dataclass(frozen=True)
class SandboxLimits:
    """Twarde limity zasobów dla kontenera agenta. Kod wygenerowany przez LLM
    jest niezaufany z definicji — nie ma tu "rozsądnych domyślnych bez
    ograniczenia", każdy przebieg jest jawnie ograniczony."""

    memory: str = "1g"
    cpus: str = "1.0"
    pids_limit: int = 256
    timeout_seconds: int = 1800


@dataclass(frozen=True)
class SandboxResult:
    """Wynik jednego przebiegu kontenera agenta — host używa tego, by
    zdecydować co dalej (snapshot `/workspace`, ocena generacji, itd.)."""

    container_name: str
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.exit_code == 0


def _docker(*args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    """`text=True` dekoduje wyjście kodowaniem z lokalnego locale (na Windows
    bywa to `cp1250`) — wyjście Dockera/kontenerów jest UTF-8 (logi agenta,
    polskie znaki w promptach), więc dekodowanie potrafi wywalić wątek
    `_readerthread` i zostawić `stdout`/`stderr` jako `None`. Jawne
    `encoding="utf-8"` naprawia to niezależnie od locale hosta."""
    return subprocess.run(
        ["docker", *args], capture_output=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def _decode(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _force_stop(container_name: str) -> None:
    """`docker kill` + `docker rm -f` — zawieszony/zapętlony agent dostaje
    SIGKILL bez ceregieli. `--rm` przy starcie zwykle posprząta kontener
    samo, ale po wymuszonym zabiciu silnik Dockera może nie zdążyć tego
    zrobić, zanim orkiestracja wraca do działania — stąd jawny `rm -f`
    jako gwarancja, że nazwa kontenera jest wolna na następną generację."""
    subprocess.run(["docker", "kill", container_name], capture_output=True, text=True)
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True)


def network_exists(name: str = _DEFAULT_NETWORK) -> bool:
    """Sprawdza, czy izolowana sieć już istnieje. Sieć (i jej `internal: true`)
    deklaruje `docker-compose.hyperagent.yml` — ten moduł zarządza wyłącznie
    cyklem życia POJEDYNCZEGO kontenera agenta na niej, nie topologią."""
    return _docker("network", "inspect", name).returncode == 0


def image_exists(tag: str = _DEFAULT_IMAGE) -> bool:
    return _docker("image", "inspect", tag).returncode == 0


def build_agent_image(tag: str = _DEFAULT_IMAGE) -> None:
    """`docker build` obrazu bazowego agenta z `sandbox/Dockerfile`.

    Obraz jest budowany RAZ i używany dla KAŻDEJ generacji — to `/workspace`
    (bind-mount, kod konkretnej generacji) się zmienia, nie obraz. Dlatego
    kontekstem budowy jest sam katalog `sandbox/` — obraz potrzebuje tylko
    runtime'u (Python + biblioteki), kod agenta przychodzi z zewnątrz."""
    proc = _docker("build", "-t", tag, str(_SANDBOX_DIR))
    if proc.returncode != 0:
        raise RuntimeError(f"docker build (agent image) nie powiódł się ({proc.returncode}):\n{proc.stderr}")


def run_agent_container(
    workspace_dir: Path,
    *,
    gateway_url: str,
    network: str = _DEFAULT_NETWORK,
    image: str = _DEFAULT_IMAGE,
    limits: SandboxLimits = SandboxLimits(),
    container_name: str | None = None,
) -> SandboxResult:
    """Odpala kontener agenta na `workspace_dir` i czeka na zakończenie albo
    przekroczenie `limits.timeout_seconds`.

    `gateway_url` (np. `http://gateway:8800`) trafia do kontenera jako JEDYNA
    poszlaka o tym, jak dotrzeć do świata zewnętrznego (env `GATEWAY_URL`) —
    w połączeniu z siecią `internal: true` to JEDYNY kierunek, w którym agent
    może faktycznie coś wysłać."""
    name = container_name or f"hyperagent-agent-{uuid.uuid4().hex[:12]}"

    run_args = [
        "run", "--rm", "--name", name,
        "--network", network,
        "--memory", limits.memory,
        "--cpus", limits.cpus,
        "--pids-limit", str(limits.pids_limit),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "-v", f"{workspace_dir}:/workspace",
        "-e", f"GATEWAY_URL={gateway_url}",
        "-w", "/workspace",
        image,
    ]

    try:
        proc = _docker(*run_args, timeout=limits.timeout_seconds)
        return SandboxResult(
            container_name=name,
            exit_code=proc.returncode,
            timed_out=False,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as e:
        _force_stop(name)
        return SandboxResult(
            container_name=name,
            exit_code=None,
            timed_out=True,
            stdout=_decode(e.stdout),
            stderr=_decode(e.stderr),
        )


# ----------------------------------------------------------------------
# Cykl życia kontenera GATEWAYA — host-side odpowiednik powyższego dla
# agenta. To wciąż tylko OPERATOR Dockera (ten sam `_docker`/`_force_stop`);
# samą izolację (i fakt, że to JEDYNY sąsiad agenta na `hyperagent_net`)
# wymusza topologia sieci zadeklarowana w `docker-compose.hyperagent.yml`.
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class GatewayHandle:
    """Uchwyt do działającego, jednogeneracyjnego gatewaya — wszystko, czego
    potrzebuje `hyperagent.loop`: `base_url` dla agenta (wewnątrz `hyperagent_net`,
    po nazwie kontenera — Docker DNS) i `stop()` do posprzątania po rundzie."""

    container_name: str
    base_url: str

    def stop(self) -> None:
        _force_stop(self.container_name)


def _wait_for_gateway_ready(name: str, *, port: int, timeout: float = 90.0, interval: float = 1.0) -> None:
    """`docker run -d` wraca, gdy kontener WYSTARTOWAŁ — nie gdy proces w
    środku zaczął faktycznie odpowiadać. Budowa `create_app` (workflow
    targetu, LLM) potrzebuje kilku-kilkunastu sekund, więc bez tej bramki
    agent odpala się natychmiast i dostaje 'connection refused' na pierwszym
    requeście, jeszcze zanim cokolwiek zostanie zalogowane.

    Sondujemy WEWNĄTRZ kontenera (`docker exec` + `urllib`, nie HTTP z hosta —
    `hyperagent_net` może nie mieć trasy z hosta). `/openapi.json` to wbudowany
    endpoint FastAPI poza `_call_logged`, więc sondowanie nie zaśmieca
    `hyperagent_gateway_log`."""
    probe = (
        "import urllib.request,sys;"
        f"urllib.request.urlopen('http://localhost:{port}/openapi.json', timeout=2);"
        "sys.exit(0)"
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _docker("exec", name, "python", "-c", probe).returncode == 0:
            return
        time.sleep(interval)
    raise RuntimeError(
        f"Gateway '{name}' nie zaczął odpowiadać w ciągu {timeout}s — sprawdź `docker logs {name}`"
    )


def gateway_image_exists(tag: str = _DEFAULT_GATEWAY_IMAGE) -> bool:
    return _docker("image", "inspect", tag).returncode == 0


def build_gateway_image(tag: str = _DEFAULT_GATEWAY_IMAGE) -> None:
    """`docker build` obrazu gatewaya — kontekst to KORZEŃ repozytorium (nie
    `hyperagent/gateway/`!), bo gateway importuje `config`/`database`/`graph`/
    `agents`/`attack_core`/`payload_attack`/`hyperagent` — patrz Dockerfile."""
    proc = _docker("build", "-f", str(_GATEWAY_DOCKERFILE), "-t", tag, str(_REPO_ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"docker build (gateway image) nie powiódł się ({proc.returncode}):\n{proc.stderr}")


def launch_gateway(
    session_id: str,
    generation_n: int,
    objective_id: str,
    *,
    network: str = _DEFAULT_NETWORK,
    db_network: str = _DEFAULT_DB_NETWORK,
    image: str = _DEFAULT_GATEWAY_IMAGE,
    port: int = _GATEWAY_PORT,
    container_name: str | None = None,
) -> GatewayHandle:
    """Odpala FRESH kontener gatewaya dla DANEJ generacji.

    `session_id`/`generation_n`/`objective_id` trafiają do niego WYŁĄCZNIE
    jako zmienne środowiskowe ustawione tu, przez hosta, raz, przed startem
    procesu — `hyperagent.gateway.server.run_from_env` czyta je dokładnie
    jeden raz i zamraża w niezmiennym `GatewayConfig`. Agent (zamknięty w
    odrębnym kontenerze, bez dostępu do tego procesu) nie ma żadnej drogi,
    by je podejrzeć czy podmienić — stąd gwarancja, że KAŻDY wpis w
    `hyperagent_gateway_log` jest wiarygodnie przypisany do tej generacji.

    Kontener dołącza do DWÓCH sieci — `docker run` przyjmuje tylko jedną
    `--network` przy starcie, więc drugą dopinamy zaraz po (`network connect`):
      • `network` (domyślnie `hyperagent_net`, `internal: true`) — JEDYNA
        trasa agenta na zewnątrz; gateway jest na niej jego jedynym sąsiadem
      • `db_network` (sieć `postgres` z głównego `docker-compose.yml`) —
        stąd (i TYLKO stąd) gateway dociera do `agent_benchmark`/`agent_audit`
        i, przez doklejony `host.docker.internal`, do Ollamy na hoście
    """
    name = container_name or f"hyperagent-gateway-{session_id[:8]}-gen{generation_n}"

    run_args = [
        "run", "-d", "--rm", "--name", name,
        "--network", network,
        "--add-host", "host.docker.internal:host-gateway",
        "-e", f"HYPERAGENT_SESSION_ID={session_id}",
        "-e", f"HYPERAGENT_GENERATION_N={generation_n}",
        "-e", f"HYPERAGENT_OBJECTIVE_ID={objective_id}",
        "-e", f"HYPERAGENT_GATEWAY_PORT={port}",
        # `config.settings` wewnątrz TEGO procesu (host) ma `db_host=localhost`/
        # `ollama_base_url=http://localhost:...` — poprawne na hoście, ale
        # wewnątrz kontenera gatewaya `localhost` to sam kontener. Nadpisujemy
        # tu jawnie na wartości prawidłowe Z PERSPEKTYWY KONTENERA, żeby
        # `audit_db`/`build_llm` (które czytają `settings` przez zmienne
        # środowiskowe — `pydantic_settings.BaseSettings`) połączyły się z
        # właściwymi usługami zamiast wywalać się 500-tką przed jakimkolwiek
        # logowaniem (patrz `_call_logged` — log idzie PRZED `fn()`, więc
        # błąd połączenia z DB w ogóle nie ma szansy się zalogować).
        "-e", f"DB_HOST={_DEFAULT_DB_HOST}",
        "-e", f"DB_PORT={settings.db_port}",
        "-e", f"DB_NAME={settings.db_name}",
        "-e", f"DB_USER={settings.db_user}",
        "-e", f"DB_PASSWORD={settings.db_password}",
        "-e", f"AUDIT_DB_NAME={settings.audit_db_name}",
        "-e", f"OLLAMA_BASE_URL={_gateway_ollama_base_url()}",
        "-e", f"OLLAMA_MODEL={settings.ollama_model}",
        image,
    ]
    proc = _docker(*run_args)
    if proc.returncode != 0:
        raise RuntimeError(f"docker run (gateway) nie powiódł się ({proc.returncode}):\n{proc.stderr}")

    connect = _docker("network", "connect", db_network, name)
    if connect.returncode != 0:
        _force_stop(name)
        raise RuntimeError(
            f"docker network connect {db_network} {name} nie powiódł się "
            f"({connect.returncode}) — bez tego gateway nie dotarłby do "
            f"Postgresa/Ollamy:\n{connect.stderr}"
        )

    try:
        _wait_for_gateway_ready(name, port=port)
    except RuntimeError:
        _force_stop(name)
        raise

    return GatewayHandle(container_name=name, base_url=f"http://{name}:{port}")
