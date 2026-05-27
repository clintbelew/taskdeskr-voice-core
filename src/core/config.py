"""
TaskDeskr Voice Core — Configuration
=====================================
Single source of truth for all environment variables and GHL constants.

IDs that are structural (pipeline stages, calendars, custom field keys) are
defined as typed constants below — they can be promoted to env vars at any
time by simply reading from settings instead of the constant.

GHL Location ID:  BsrmNxNTZZ6OsEosQFuo
GHL Pipeline:     El Jefe - Law Firm Demo  (qTGXyS5rpHPni3XRgDyD)
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
    APP_VERSION: str = "2.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # ── Vapi ──────────────────────────────────────────────────────────────────
    VAPI_WEBHOOK_SECRET: str = Field(default="", description="Vapi webhook signing secret")

    # ── LLM Providers ─────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key (optional — not used when DEFAULT_LLM_PROVIDER=anthropic)")
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic Claude API key")

    DEFAULT_LLM_PROVIDER: Literal["openai", "anthropic", "auto"] = "anthropic"
    OPENAI_MODEL: str = "gpt-4.1-mini"
    ANTHROPIC_MODEL: str = "claude-haiku-4-5-20251029"         # Conversation model (low latency — Haiku is 3-4x faster than Sonnet)
    ANTHROPIC_SUMMARY_MODEL: str = "claude-opus-4-5"    # Summary/analysis model (high quality)

    # ── GoHighLevel ───────────────────────────────────────────────────────────
    GHL_API_KEY: str = Field(..., description="GoHighLevel Bearer token (v2 Private Integration Key)")
    GHL_LOCATION_ID: str = Field(default="BsrmNxNTZZ6OsEosQFuo", description="GHL Location ID")
    GHL_TIMEZONE: str = "America/Chicago"
    GHL_SMS_FROM_NUMBER: str = Field(default="+12108995511", description="GHL approved phone number for outbound SMS")

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="",
        description="Redis connection URL (redis://... or rediss://...). Leave empty to use in-memory fallback."
    )

    # ── Escalation ────────────────────────────────────────────────────────────
    ESCALATION_PHONE_NUMBER: str = Field(
        default="", description="Phone number to transfer escalated calls to"
    )


# ─────────────────────────────────────────────────────────────────────────────
# GHL Structural Constants
# These are stable GHL IDs extracted from the TaskDeskr sub-account.
# To promote any of these to env vars, replace the literal with:
#   settings.GHL_PIPELINE_ID  (after adding it to Settings above)
# ─────────────────────────────────────────────────────────────────────────────

class GHLPipeline:
    """El Jefe - Law Firm Demo — qTGXyS5rpHPni3XRgDyD"""
    PIPELINE_ID = "qTGXyS5rpHPni3XRgDyD"

    class Stages:
        # El Jefe - Law Firm Demo stages
        NEW_LEAD                = "17677624-40c1-4ca6-9cc1-cdbd0514481d"
        INTAKE_COMPLETED        = "3c20c16e-ba75-42a7-aa48-2ed7818ceb31"
        CONSULTATION_REQUESTED  = "afa3eebd-d369-47bb-bf86-e238a9e8e74b"
        RETAINED                = "4f2591d1-d8a7-4c18-9d6e-8cb68f6dfe26"
        NOT_QUALIFIED           = "c329c64f-31f7-479a-85ad-578610ad36df"

        # Aliases for backward compatibility with dispatcher.py references
        BOOKING_LINK_SENT   = INTAKE_COMPLETED     # maps to Intake Completed
        APPOINTMENT_BOOKED  = CONSULTATION_REQUESTED  # maps to Consultation Requested
        CONFIRMED_SHOWED    = RETAINED             # maps to Retained
        NO_SHOW             = NOT_QUALIFIED        # maps to Not Qualified
        CONVERTED           = RETAINED             # maps to Retained
        DISQUALIFIED        = NOT_QUALIFIED        # maps to Not Qualified


class GHLCalendars:
    """Calendars available in the TaskDeskr sub-account."""
    PERSONAL           = "5K0hLjasj81cHyeSK6Xn"   # Clint Belew's Personal Calendar
    EXISTING_PATIENT   = "ZIU1fcCPtqunLcVpPWx1"   # Existing Patient Scheduling Template
    NEW_PATIENT        = "AewaSaTHTTYUBFqFJ9Yg"    # New Patient Scheduling Template

    # Default calendar for Phase 1 (new inbound leads / demo bookings)
    # Must match GHL_CALENDAR_ID in ghl.py — both point to Clint's Personal Calendar
    DEFAULT = PERSONAL


class GHLCustomFields:
    """
    Custom field IDs for contact qualification.
    These are the actual GHL field IDs (not keys) required by the v2 API.
    Verified against location BsrmNxNTZZ6OsEosQFuo on 2026-04-03.
    """
    # Standard intake fields — use field ID (not fieldKey) in API calls
    INSURANCE_STATUS   = "hNpVIDD7mqZSL6daaR4t"   # Do you have health insurance?
    INSURANCE_PROVIDER = "Wv9qtchGAUaiqgx70M7B"   # Insurance Provider
    INSURANCE_PHONE    = "pf20Eb3VyVvqZJTGZp2o"   # Insurance Phone #
    MEMBER_ID          = "fGkhFB7oMPSrxfqcw9fm"   # Member ID
    GROUP_NUMBER       = "g9Cd7I7k3YtBX1mqpi21"   # Group Number
    CHIEF_COMPLAINT    = "fkS6unsGraaWIrutNmK9"   # Briefly list your chief complaint
    REFERRAL_SOURCE    = "D1cru9E5LnnYRnNSBpLr"   # How did you hear about our office?
    QUESTION_CONCERN   = "HnWxcFdqIZ7TyJ7goJzA"   # Question or Concern
    VISIT_COUNT        = "n2oJQBmTn7xo6ja7aZYe"   # Appointment Visit Count


class GHLUsers:
    """Known user IDs for assignment."""
    CLINT_BELEW  = "CT0EbffzObctAF9xhxTQ"
    JEWEL_PEREZ  = "C7nLjkmLtSDHpD938Ke3"

    # Default assigned user for new voice bot leads
    DEFAULT_ASSIGNED = CLINT_BELEW


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
