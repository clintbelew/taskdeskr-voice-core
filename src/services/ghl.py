"""
TaskDeskr Voice Core — GoHighLevel Service
===========================================
Handles all communication with the GoHighLevel (GHL) REST API v1.

Capabilities:
  - Contact lookup by phone number
  - Contact upsert (create or update)
  - Appointment booking
  - Tag management (add/remove)
  - Note creation
  - Outbound SMS via GHL
  - Pipeline opportunity management
  - Custom field updates

All methods are async and return typed dicts.
Errors are logged and re-raised as GHLError for clean upstream handling.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

GHL_BASE = "https://rest.gohighlevel.com/v1"


class GHLError(Exception):
    """Raised when a GoHighLevel API call fails."""

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# ── HTTP client ───────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.GHL_API_KEY}",
        "Content-Type": "application/json",
    }


def _raise_for_status(response: httpx.Response, context: str) -> None:
    if response.status_code not in (200, 201):
        logger.error(
            f"GHL API error in {context}",
            extra={"status": response.status_code, "body": response.text[:500]},
        )
        raise GHLError(
            f"GHL {context} failed with status {response.status_code}",
            status_code=response.status_code,
            body=response.text,
        )


# ── Contact operations ────────────────────────────────────────────────────────

async def lookup_contact_by_phone(phone: str) -> Optional[dict[str, Any]]:
    """
    Search GHL for a contact matching the given phone number.
    Returns the first match or None if not found.
    """
    # Normalize to E.164 if not already
    normalized = _normalize_phone(phone)
    url = f"{GHL_BASE}/contacts/"
    params = {"locationId": settings.GHL_LOCATION_ID, "query": normalized}

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, headers=_headers(), params=params)

    if response.status_code == 200:
        data = response.json()
        contacts = data.get("contacts", [])
        if contacts:
            logger.info(
                "GHL contact found",
                extra={"contact_id": contacts[0].get("id"), "phone": normalized},
            )
            return contacts[0]
        logger.info("GHL contact not found", extra={"phone": normalized})
        return None

    logger.warning(
        "GHL contact lookup returned non-200",
        extra={"status": response.status_code, "phone": normalized},
    )
    return None


async def upsert_contact(
    phone: str,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
    custom_fields: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    Create or update a GHL contact. Returns the full contact object.
    GHL's v1 API upserts by phone number automatically.
    """
    payload: dict[str, Any] = {
        "phone": _normalize_phone(phone),
        "locationId": settings.GHL_LOCATION_ID,
    }
    if first_name:
        payload["firstName"] = first_name
    if last_name:
        payload["lastName"] = last_name
    if email:
        payload["email"] = email
    if custom_fields:
        payload["customField"] = [
            {"id": k, "field_value": v} for k, v in custom_fields.items()
        ]

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{GHL_BASE}/contacts/", headers=_headers(), json=payload
        )

    _raise_for_status(response, "upsert_contact")
    data = response.json()
    contact = data.get("contact") or data
    logger.info("GHL contact upserted", extra={"contact_id": contact.get("id")})
    return contact


async def get_contact(contact_id: str) -> dict[str, Any]:
    """Fetch a contact by ID."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{GHL_BASE}/contacts/{contact_id}", headers=_headers()
        )
    _raise_for_status(response, "get_contact")
    return response.json().get("contact", response.json())


# ── Appointment booking ───────────────────────────────────────────────────────

async def book_appointment(
    contact_id: str,
    start_time_iso: str,
    title: str = "Appointment",
    calendar_id: Optional[str] = None,
    notes: str = "",
) -> dict[str, Any]:
    """
    Book an appointment in GHL for the given contact.

    Parameters
    ----------
    contact_id     : GHL contact ID
    start_time_iso : ISO 8601 datetime string (e.g. "2026-04-01T14:00:00")
    title          : Appointment title shown in GHL calendar
    calendar_id    : Override the default calendar; falls back to GHL_CALENDAR_ID
    notes          : Optional appointment notes
    """
    cal_id = calendar_id or settings.GHL_CALENDAR_ID
    if not cal_id:
        raise GHLError("No calendar ID configured. Set GHL_CALENDAR_ID in .env.")

    payload: dict[str, Any] = {
        "calendarId": cal_id,
        "contactId": contact_id,
        "startTime": start_time_iso,
        "title": title,
        "locationId": settings.GHL_LOCATION_ID,
        "selectedTimezone": settings.GHL_TIMEZONE,
    }
    if notes:
        payload["notes"] = notes

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{GHL_BASE}/appointments/", headers=_headers(), json=payload
        )

    _raise_for_status(response, "book_appointment")
    appt = response.json()
    logger.info(
        "Appointment booked",
        extra={"contact_id": contact_id, "start_time": start_time_iso},
    )
    return appt


# ── Tags ──────────────────────────────────────────────────────────────────────

async def add_tags(contact_id: str, tags: list[str]) -> dict[str, Any]:
    """Add one or more tags to a GHL contact."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{GHL_BASE}/contacts/{contact_id}/tags/",
            headers=_headers(),
            json={"tags": tags},
        )
    _raise_for_status(response, "add_tags")
    logger.info("Tags added", extra={"contact_id": contact_id, "tags": tags})
    return response.json()


async def remove_tags(contact_id: str, tags: list[str]) -> dict[str, Any]:
    """Remove one or more tags from a GHL contact."""
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.delete(
            f"{GHL_BASE}/contacts/{contact_id}/tags/",
            headers=_headers(),
            json={"tags": tags},
        )
    _raise_for_status(response, "remove_tags")
    logger.info("Tags removed", extra={"contact_id": contact_id, "tags": tags})
    return response.json()


# ── Notes ─────────────────────────────────────────────────────────────────────

async def add_note(contact_id: str, body: str, user_id: str = "") -> dict[str, Any]:
    """Add a note to a GHL contact's timeline."""
    payload: dict[str, Any] = {"body": body, "contactId": contact_id}
    if user_id:
        payload["userId"] = user_id

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{GHL_BASE}/contacts/{contact_id}/notes/",
            headers=_headers(),
            json=payload,
        )
    _raise_for_status(response, "add_note")
    logger.info("Note added", extra={"contact_id": contact_id})
    return response.json()


# ── SMS ───────────────────────────────────────────────────────────────────────

async def send_sms(
    contact_id: str,
    message: str,
    from_number: str = "",
) -> dict[str, Any]:
    """
    Send an outbound SMS to a contact via GHL Conversations API.
    `from_number` should be the GHL phone number (e.g. "+15125551234").
    """
    payload: dict[str, Any] = {
        "type": "SMS",
        "contactId": contact_id,
        "message": message,
    }
    if from_number:
        payload["fromNumber"] = from_number

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{GHL_BASE}/conversations/messages/outbound",
            headers=_headers(),
            json=payload,
        )
    _raise_for_status(response, "send_sms")
    logger.info("SMS sent", extra={"contact_id": contact_id})
    return response.json()


# ── Pipeline / Opportunity ────────────────────────────────────────────────────

async def create_opportunity(
    contact_id: str,
    name: str,
    pipeline_id: Optional[str] = None,
    stage_id: str = "",
    monetary_value: float = 0.0,
) -> dict[str, Any]:
    """Create a pipeline opportunity linked to a contact."""
    pid = pipeline_id or settings.GHL_PIPELINE_ID
    if not pid:
        raise GHLError("No pipeline ID configured. Set GHL_PIPELINE_ID in .env.")

    payload: dict[str, Any] = {
        "pipelineId": pid,
        "locationId": settings.GHL_LOCATION_ID,
        "name": name,
        "contactId": contact_id,
        "monetaryValue": monetary_value,
        "status": "open",
    }
    if stage_id:
        payload["pipelineStageId"] = stage_id

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{GHL_BASE}/opportunities/", headers=_headers(), json=payload
        )
    _raise_for_status(response, "create_opportunity")
    logger.info("Opportunity created", extra={"contact_id": contact_id, "name": name})
    return response.json()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Strip non-digit characters and ensure E.164 format (+1XXXXXXXXXX)."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}"
