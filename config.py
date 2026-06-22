from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:20b"  # model SYSTEMU DOCELOWEGO (agenci)

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
