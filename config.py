from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:20b"

    # Przechwytywanie thinkingu agentów do bazy logów (agent_logs). Wymaga modelu
    # rozumującego (np. gpt-oss); włącza tryb `reasoning` w Ollamie, dzięki któremu
    # reasoning trafia do osobnego kanału (reasoning_content) zamiast do treści.
    capture_thinking: bool = True

    # Model napędzający meta-attackera w pętli self-improving (redteam/).
    # None → fallback na ollama_model/ollama_base_url (ten sam stack co agenci).
    meta_attacker_model: str | None = None
    meta_attacker_base_url: str | None = None

    # Model napędzający hyperagenta (przez gateway — agent nigdy nie łączy się
    # z Ollamą bezpośrednio). None → fallback na ollama_model/ollama_base_url.
    hyperagent_model: str | None = None
    hyperagent_base_url: str | None = None

    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "agent_benchmark"
    db_user: str = "postgres"
    db_password: str = "postgres"
    audit_db_name: str = "agent_audit"
    logs_db_name: str = "agent_logs"

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


settings = Settings()
