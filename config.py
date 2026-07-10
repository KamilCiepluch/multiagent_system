from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Model systemu docelowego (agenci/supervisor) — lokalny stack Ollama.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:20b"
    # Małe okno Ollamy (~4096) przepełnia się (prompt + skille + wyniki) → model gubi reguły/zapętla.
    ollama_num_ctx: int = 16384
    # Domyślne ~0.8 za wysokie — sypie tool-calle/structured output; niska stabilizuje łańcuch delegacji.
    agent_temperature: float = 0.2
    # Reasoning agentów do osobnego kanału → agent_logs. Wymaga modelu rozumującego (np. gpt-oss).
    capture_thinking: bool = True
    # Super-kroki grafu ReAct (~2× liczba tool-calli); powyżej ~150 to zwykle palenie czasu.
    agent_recursion_limit: int = 100
    # Deterministyczne dopięcie zgubionego 2. hopa. OFF celowo — delegację ma decydować model
    # (docs/architecture.md §5). Włącz env COMPLETION_GUARD=true tylko do porównań.
    completion_guard: bool = False

    # Meta-attacker pętli self-improving (payload_attack/). None → fallback na ollama_*.
    meta_attacker_model: str | None = None
    meta_attacker_base_url: str | None = None
    # Hyperagent (łączy się przez gateway, nie wprost z Ollamą). None → fallback na ollama_*.
    hyperagent_model: str | None = None
    hyperagent_base_url: str | None = None
    # Retrieval top-k strategii (agent_audit.attack_strategies) do promptu hiperagenta.
    strategy_top_k: int = 5

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "agent_benchmark"
    # Świat-cel benchmarku. Rejestr: attack_core/runner.py::DATASETS. Override: env BENCHMARK_DATASET.
    benchmark_dataset: str = "attack_v1"
    db_user: str = "postgres"
    db_password: str = "postgres"
    # Jeden silnik agent_core, schematy (logs/audit/knowledge/recon) adresowane przez search_path per moduł.
    core_db_name: str = "agent_core"
    audit_db_name: str = "agent_core"  # = core (hyperagent/sandbox czyta tę nazwę)
    logs_db_name: str = "agent_core"   # = core
    # Strefa renderu znaczników czasu (TIMESTAMPTZ trzyma UTC; sesja DB decyduje o renderze).
    display_tz: str = "Europe/Warsaw"
    # Osobna baza obserwowalności pętli hyperagent_email (niezależna od agent_logs/agent_audit).
    hyperagent_logs_name: str = "hyperagent_logs"

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    def _core_dsn(self, schema: str) -> str:
        """DSN do agent_core z search_path na `schema` i strefą sesji = display_tz."""
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
        return self._core_dsn("recon")

    @property
    def hyperagent_logs_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.hyperagent_logs_name}"
        )


settings = Settings()
