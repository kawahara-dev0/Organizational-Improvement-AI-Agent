from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────
    database_url: str = "postgresql://oiagent:oiagent@localhost:5432/oiagent"

    # ── Supabase (production) ─────────────────────────────────
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    # ── AI Models ─────────────────────────────────────────────
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    # ── Feature flags ─────────────────────────────────────────
    enable_claude_routing: bool = False

    # ── App ───────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"


settings = Settings()
