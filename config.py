from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:20b"  # model SYSTEMU DOCELOWEGO (agenci)

    # Provider LLM systemu docelowego (agenci/supervisor). 'ollama' = lokalny (domyślnie,
    # bez zmian); 'nvidia' = ChatNVIDIA (build.nvidia.com / NIM). Override: env LLM_PROVIDER.
    # Przełącznik pozwala testować system na mocnym modelu API bez protez pod słaby lokalny.
    llm_provider: str = "ollama"
    # Model dla providera 'nvidia' (np. 'meta/llama-3.3-70b-instruct',
    # 'nvidia/llama-3.1-nemotron-70b-instruct', 'qwen/qwen2.5-72b-instruct'). Env NVIDIA_MODEL.
    # Klucz API: ChatNVIDIA czyta go automatycznie ze zmiennej env NVIDIA_API_KEY.
    nvidia_model: str = "meta/llama-3.3-70b-instruct"
    # Pusty = domyślny endpoint build.nvidia.com; ustaw dla self-hosted NIM. Env NVIDIA_BASE_URL.
    nvidia_base_url: str = ""
    # Klucz API NVIDIA. Najlepiej wpisać do pliku .env jako NVIDIA_API_KEY=nvapi-... (nie trafi
    # wtedy do komend/logów). Pusty → ChatNVIDIA spróbuje wziąć go z env NVIDIA_API_KEY.
    nvidia_api_key: str = ""

    # Completion-guard: deterministyczne dopięcie zgubionego 2. hopa (supervisor→egzekutor).
    # DOMYŚLNIE WYŁĄCZONY (False) — architektura wzorcowa wymaga, by o delegacji decydował MODEL,
    # a nie sztuczna proteza. Żadne domykanie nie może maskować (nie)zdolności modelu do orkiestracji
    # ani decydować za niego — inaczej test modeli jest nierzetelny (patrz docs: tradeoff
    # reliability↔authority). Włącz env COMPLETION_GUARD=true tylko do świadomych porównań.
    completion_guard: bool = False

    # Przechwytywanie thinkingu agentów do bazy logów (agent_logs). Wymaga modelu
    # rozumującego (np. gpt-oss); włącza tryb `reasoning` w Ollamie, dzięki któremu
    # reasoning trafia do osobnego kanału (reasoning_content) zamiast do treści.
    capture_thinking: bool = True

    # Limit super-kroków grafu ReAct (agent + supervisor). 50 ≈ ~25 wywołań narzędzi.
    # Zwiększ, gdy złożone zadania nie mieszczą się w krokach; powyżej ~150 to zwykle
    # palenie czasu (zapętlony model rzadko się odplącze, a czas/tokeny rosną liniowo).
    agent_recursion_limit: int = 100

    # Okno kontekstu Ollamy dla modeli systemu docelowego (agenci/supervisor). Domyślne
    # Ollamy bywa małe (~4096) — długi system prompt + skille + wyniki narzędzi je
    # przepełniają, model "zapomina" reguły i się gubi/zapętla. Większe = stabilniej,
    # ale więcej VRAM (KV-cache). Gdy mimo to się gubi — podnieś do 16384.
    ollama_num_ctx: int = 16384

    # Temperatura próbkowania agentów/supervisora. Domyślna Ollamy (~0.8) jest ZA WYSOKA dla
    # niezawodnego wykonywania procedur tool-callowych — powoduje wariancję: halucynowane ID
    # maili, sypiący się structured output, raz dobry/raz zły wybór egzekutora, zbędne pętlenie.
    # Niska temperatura stabilizuje łańcuch delegacji (supervisor → email_agent → egzekutor).
    # Override przez env AGENT_TEMPERATURE.
    agent_temperature: float = 0.2

    # Model napędzający meta-attackera w pętli self-improving (payload_attack/).
    # None → fallback na ollama_model/ollama_base_url (ten sam stack co agenci).
    meta_attacker_model: str | None = None
    meta_attacker_base_url: str | None = None

    # Model napędzający hyperagenta (przez gateway — agent nigdy nie łączy się
    # z Ollamą bezpośrednio). None → fallback na ollama_model/ollama_base_url.
    hyperagent_model: str | None = None
    hyperagent_base_url: str | None = None

    # Ile strategii z biblioteki (agent_audit.attack_strategies) pobierać do
    # promptu hiperagenta na początku każdej generacji (retrieval top-k po cosine).
    strategy_top_k: int = 5

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "agent_benchmark"
    # Wybór podmienialnego zestawu danych świata-celu (agent_benchmark). 'attack_v1' = aktywny scenariusz
    # ataku (role-graded cross-agent + złośliwe repo); 'default' = oryginalne seedy. Override: env
    # BENCHMARK_DATASET. Rejestr: attack_core/runner.py::DATASETS.
    benchmark_dataset: str = "attack_v1"
    db_user: str = "postgres"
    db_password: str = "postgres"
    # Skonsolidowana baza: jeden silnik, trzy schematy (logs / audit / knowledge).
    # logs+audit+knowledge żyją w agent_core; adresowane przez search_path per moduł.
    core_db_name: str = "agent_core"
    audit_db_name: str = "agent_core"  # = core (zachowane: hyperagent/sandbox czyta tę nazwę)
    logs_db_name: str = "agent_core"   # = core
    # Strefa renderowania znaczników czasu (TIMESTAMPTZ trzyma UTC; sesja DB decyduje,
    # w jakiej strefie klient je dostaje). Ustawiamy na lokalną, by widoki (trace/show_*)
    # pokazywały to samo co klient DB. Override przez env DISPLAY_TZ.
    display_tz: str = "Europe/Warsaw"
    # Dedykowana baza obserwowalności pętli hyperagent_email — niezależna od
    # agent_audit/agent_logs (hyperagent czyta tamte jako logi atakowanego
    # systemu, więc własne logi trzyma osobno).
    hyperagent_logs_name: str = "hyperagent_logs"

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    def _core_dsn(self, schema: str) -> str:
        """DSN do agent_core z search_path na dany schemat oraz strefą czasową sesji
        ustawioną na display_tz. search_path: moduł DAL widzi swoje tabele bez kwalifikacji
        (cross-schema kwalifikujemy jawnie). TimeZone: viewery renderują czas lokalnie,
        spójnie z klientem DB (TIMESTAMPTZ i tak trzyma UTC — to tylko render)."""
        from urllib.parse import quote
        opts = quote(f"-c search_path={schema} -c TimeZone={self.display_tz}", safe="")
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.core_db_name}?options={opts}"
        )

    @property
    def audit_db_dsn(self) -> str:
        return self._core_dsn("audit")

    @property
    def logs_db_dsn(self) -> str:
        return self._core_dsn("logs")

    @property
    def knowledge_db_dsn(self) -> str:
        return self._core_dsn("knowledge")

    @property
    def recon_db_dsn(self) -> str:
        """Schemat `recon` w agent_core — benchmark podatności atakowanego modelu (Garak)."""
        return self._core_dsn("recon")

    @property
    def hyperagent_logs_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.hyperagent_logs_name}"
        )


settings = Settings()
