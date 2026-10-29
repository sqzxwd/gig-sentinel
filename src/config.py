"""Configuration settings for Gig Sentinel service using pydantic-settings."""

from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram Bot Token (required for live bot)
    bot_token: SecretStr = Field(
        default=SecretStr("mock_token_for_tests"),
        description="Telegram Bot API Token from @BotFather",
    )

    # AI Pitcher Settings
    ai_api_key: SecretStr | None = Field(
        default=None,
        description="API Key for AI Pitch Generator (Gemini or OpenAI-compatible)",
    )
    ai_api_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta",
        description="Base URL for LLM API",
    )
    ai_model: str = Field(
        default="gemini-2.5-flash",
        description="Model identifier for pitch generation",
    )

    # Freelance RSS Feed Settings
    habr_rss_url: HttpUrl = Field(
        default=HttpUrl("https://freelancehunt.com/projects.rss"),
        description="Habr Freelance RSS tasks feed URL",
    )
    poll_interval_seconds: int = Field(
        default=120,
        ge=10,
        description="Interval in seconds between RSS polling cycles",
    )
    request_timeout: float = Field(
        default=15.0,
        gt=0.0,
        description="HTTP request timeout in seconds",
    )

    # Database & Storage Settings
    db_path: Path = Field(
        default=Path("data/gig_sentinel.db"),
        description="Path to SQLite database file",
    )

    # Service & Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    @property
    def is_ai_configured(self) -> bool:
        """Check if an external AI API key is configured."""
        return bool(self.ai_api_key and self.ai_api_key.get_secret_value().strip())

    def get_db_path(self) -> Path:
        """Ensure parent directory exists and return absolute database path."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        return self.db_path


# Global cached settings instance
settings = Settings()
