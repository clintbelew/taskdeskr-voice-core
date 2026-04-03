"""
TaskDeskr Voice Core — Configuration
=====================================
Single source of truth for all environment variables and GHL constants.

IDs that are structural (pipeline stages, calendars, custom field keys) are
defined as typed constants below — they can be promoted to env vars at any
time by simply reading from settings instead of the constant.

GHL Location ID:  BsrmNxNTZZ6OsEosQFuo
GHL Pipeline:     Voice Bot Pipeline  (zoFFyj9AhfeMiGeaTaqh)
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
    APP_VERSION: str = "1.1.0"
    PORT: int = 8000
    DEBUG: bool = False

    # ── Vapi ──────────────────────────────────────────────────────────────────
    VAPI_WEBHOOK_SECRET: str = Field(default="", description="Vapi webhook signing secret")

    # ── LLM Providers ─────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key")
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic Claude API key")

    DEFAULT_LLM_PROVIDER: Literal["openai", "anthropic", "auto"] = "openai"
    OPENAI_MODEL: str = "gpt-4.1-mini"
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"

    # ── GoHighLevel ───────────────────────────────────────────────────────────
    GHL_API_KEY: str = Field(..., description="GoHighLevel Bearer token (v2 Private Integration Key)")
    GHL_LOCATION_ID: str = Field(default="BsrmNxNTZZ6OsEosQFuo", description="GHL Location ID")
    GHL_TIMEZONE: str = "America/Chicago"

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
    """Voice Bot Pipeline — zoFFyj9AhfeMiGeaTaqh"""
    PIPELINE_ID = "zoFFyj9AhfeMiGeaTaqh"

    class Stages:
        NEW_LEAD            = "c7b87774-87ed-4297-b5fd-c80232b06e3d"
        BOOKING_LINK_SENT   = "fb95cee1-80a0-444d-a971-f0886b6966bb"
        APPOINTMENT_BOOKED  = "4749ca93-a22c-4e2b-b1a0-a695dacd6608"
        CONFIRMED_SHOWED    = "9a1a6cd2-d96a-4893-9009-218c491ab916"
        NO_SHOW             = "150e6fe5-04e9-4b43-8223-c8384d72ec30"
        CONVERTED           = "33e671f8-6851-4655-9ad8-304e35a6d8d2"
        DISQUALIFIED        = "20a039b3-10ce-47d4-99e4-e04147845301"


class GHLCalendars:
    """Calendars available in the TaskDeskr sub-account."""
    PERSONAL           = "5K0hLjasj81cHyeSK6Xn"   # Clint Belew's Personal Calendar
    EXISTING_PATIENT   = "ZIU1fcCPtqunLcVpPWx1"   # Existing Patient Scheduling Template
    NEW_PATIENT        = "AewaSaTHTTYUBFqFJ9Yg"    # New Patient Scheduling Template

    # Default calendar for Phase 1 (new inbound leads)
    DEFAULT = NEW_PATIENT


class GHLCustomFields:
    """
    Custom field keys for contact qualification.
    Use these as the 'key' parameter in GHL API PATCH calls.
    """
    # Standard intake fields
    INSURANCE_STATUS   = "contact.do_you_have_health_insurance"
    INSURANCE_PROVIDER = "contact.insurance_provider"
    INSURANCE_PHONE    = "contact.insurance_phone"
    MEMBER_ID          = "contact.member_id"
    GROUP_NUMBER       = "contact.group_number"
    CHIEF_COMPLAINT    = "contact.briefly_list_your_chief_compliant_or_symptom_s"
    REFERRAL_SOURCE    = "contact.how_did_you_hear_about_our_office"
    QUESTION_CONCERN   = "contact.question_or_concern"
    VISIT_COUNT        = "contact.appointment_visit_count"


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
