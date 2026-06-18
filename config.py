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
    audit_db_name: str = "agent_audit"
    logs_db_name: str = "agent_logs"
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

    @property
    def audit_db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.audit_db_name}"
        )

    @property
    def logs_db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.logs_db_name}"
        )

    @property
    def hyperagent_logs_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.hyperagent_logs_name}"
        )


settings = Settings()
