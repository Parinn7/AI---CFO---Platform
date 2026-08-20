"""Application configuration.

Settings are loaded from environment variables (and a local `.env` file in
development). Secrets — the database URL, JWT secret, and LLM API key — are
never committed to git; see `.env.example` for the expected shape.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "AI CFO Platform API"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"

    # --- Database ---
    # SQLAlchemy async URL, e.g.
    #   postgresql+psycopg://user:password@localhost:5432/ai_cfo
    # Left empty until a Postgres instance is provisioned; the health check
    # reports the DB as "not_configured" in that case rather than crashing.
    database_url: str = ""

    # --- Security (used from Phase 2 onward) ---
    jwt_secret: str = "dev-insecure-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    # Password-reset links are short-lived (task 2.4, FR-1.4).
    reset_token_expire_minutes: int = 30

    # --- LLM provider (used from Phase 7 onward) ---
    llm_provider: str = "openai"
    llm_api_key: str = ""

    # --- CORS ---
    # Comma-separated list of allowed frontend origins.
    cors_origins: str = "http://localhost:3000"

    # Public base URL of the frontend — used to build password-reset links.
    frontend_base_url: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
