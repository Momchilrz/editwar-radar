"""Runtime configuration. Environment variables override the defaults; see .env.example."""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Edit-War Radar settings. Field names map to uppercase environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    wikis: str = "en.wikipedia.org"
    window_hours: float = 6
    refresh_seconds: int = 60
    ua_contact: str = "your@email"
    database_url: str = "sqlite:///./data/editwar.db"
    skip_minor: bool = False
    main_namespace_only: bool = True
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000
    leaderboard_min_reverts: int = 2
    stream_url: str = "https://stream.wikimedia.org/v2/stream/recentchange"
    stream_connect_timeout: float = 10
    stream_read_timeout: float = 120
    backfill: bool = True
    disable_ingest: bool = False
    trust_env: bool = True
    http_min_interval: float = Field(default=0.25, ge=0)

    @field_validator("wikis")
    @classmethod
    def _wikis_nonempty(cls, value: str) -> str:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts:
            raise ValueError("WIKIS must list at least one server_name")
        return ",".join(parts)

    @field_validator("window_hours")
    @classmethod
    def _window_positive(cls, value: float) -> float:
        if value <= 0 or value > 48:
            raise ValueError("WINDOW_HOURS must be between 0 and 48")
        return value

    @field_validator("refresh_seconds")
    @classmethod
    def _refresh_floor(cls, value: int) -> int:
        if value < 5:
            raise ValueError("REFRESH_SECONDS must be >= 5")
        return value

    @field_validator("leaderboard_min_reverts")
    @classmethod
    def _min_reverts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("LEADERBOARD_MIN_REVERTS must be >= 1")
        return value

    @property
    def wiki_set(self) -> frozenset[str]:
        return frozenset(part.strip().lower() for part in self.wikis.split(",") if part.strip())

    @property
    def user_agent(self) -> str:
        contact = self.ua_contact.replace("\r", "").replace("\n", "").strip() or "unset@example.com"
        return f"EditWarRadar/0.1 (contact: {contact})"

    @property
    def placeholder_contact(self) -> bool:
        contact = self.ua_contact.strip().lower()
        return contact in {
            "",
            "your@email",
            "you@example.com",
            "unset@example.com",
        } or contact.endswith("@example.com")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def setup_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sseclient").setLevel(logging.WARNING)
