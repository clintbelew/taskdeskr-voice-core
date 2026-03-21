"""
TaskDeskr Voice Core — Configuration
=====================================
Single source of truth for all environment variables.
Uses pydantic-settings for validation and .env file support.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Application ───────────────────────────────────────────────────────────
    APP_NAME: str = "TaskDeskr Voice Core"
    APP_VERSION: str = "1.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # ── Vapi ──────────────────────────────────────────────────────────────────
    # Used to verify inbound webhook signatures from Vapi
    VAPI_WEBHOOK_SECRET: str = Field(default="", description="Vapi webhook signing secret")

    # ── LLM Providers ─────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key")
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic Claude API key")

    # Routing: "openai" | "anthropic" | "auto"
    # "auto" uses Claude for summarization/reasoning, GPT for everything else
    DEFAULT_LLM_PROVIDER: Literal["openai", "anthropic", "auto"] = "openai"
    OPENAI_MODEL: str = "gpt-4.1-mini"
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"

    # ── GoHighLevel ───────────────────────────────────────────────────────────
    GHL_API_KEY: str = Field(..., description="GoHighLevel Bearer token (v1 API key)")
    GHL_LOCATION_ID: str = Field(..., description="GoHighLevel Location ID")
    GHL_CALENDAR_ID: str = Field(default="", description="Default GHL Calendar ID")
    GHL_PIPELINE_ID: str = Field(default="", description="GHL Pipeline ID for deal tracking")
    GHL_TIMEZONE: str = "America/Chicago"

    # ── Escalation ────────────────────────────────────────────────────────────
    ESCALATION_PHONE_NUMBER: str = Field(
        default="", description="Phone number to transfer escalated calls to"
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
