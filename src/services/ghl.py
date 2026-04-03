"""
TaskDeskr Voice Core — GoHighLevel Service
===========================================
Handles all communication with the GoHighLevel REST API (v2).

Phase 1 capabilities:
  1. lookup_or_create_contact  — find by phone, create if missing
  2. update_qualification_fields — save intake custom fields to contact
  3. create_opportunity        — open a deal in the Voice Bot Pipeline
  4. move_opportunity_stage    — advance the deal stage (e.g. → Booking Link Sent)
  5. add_note                  — log structured call summary to contact timeline
  6. add_tags                  — tag contacts (e.g. "voice-bot-lead")
  7. send_sms                  — outbound SMS via GHL Conversations

All methods are async. Errors raise GHLError with status code and body for
clean upstream handling. No silent failures.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from src.core.config import GHLCustomFields, GHLPipeline, GHLUsers, settings
from src.core.logger import get_logger

logger = get_logger(__name__)

# GHL v2 API base — use v2 for contacts/opportunities, v1 for legacy endpoints
GHL_V2 = "https://services.leadconnectorhq.com"
GHL_V1 = "https://rest.gohighlevel.com/v1"

# GHL v2 requires a different header format
def _headers_v2() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.GHL_API_KEY}",
        "Content-Type": "application/json",
        "Version": "2021-07-28",
    }


def _headers_v1() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.GHL_API_KEY}",
        "Content-Type": "application/json",
    }


class GHLError(Exception):
    """Raised when a GoHighLevel API call fails."""

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _raise_for_status(response: httpx.Response, context: str) -> None:
    if response.status_code not in (200, 201):
        logger.error(
            f"GHL API error in {context}",
            extra={"status": response.status_code, "body": response.text[:500]},
        )
        raise GHLError(
            f"GHL {context} failed with HTTP {response.status_code}",
            status_code=response.status_code,
            body=response.text,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Contact Operations
# ─────────────────────────────────────────────────────────────────────────────

async def lookup_contact_by_phone(phone: str) -> Optional[dict[str, Any]]:
    """
    Search GHL for a contact matching the given phone number.
    Returns the first match or None if not found.
    Uses v1 search endpoint which is stable for phone lookup.
    """
    normalized = _normalize_phone(phone)
    url = f"{GHL_V1}/contacts/"
    params = {"locationId": settings.GHL_LOCATION_ID, "query": normalized}

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(url, headers=_headers_v1(), params=params)

    if response.status_code == 200:
        contacts = response.json().get("contacts", [])
        if contacts:
            contact = contacts[0]
            logger.info(
                "GHL contact found by phone",
                extra={"contact_id": contact.get("id"), "phone": normalized},
            )
            return contact
        logger.info("GHL contact not found by phone", extra={"phone": normalized})
        return None

    logger.warning(
        "GHL phone lookup returned unexpected status",
        extra={"status": response.status_code, "phone": normalized},
    )
    return None


async def create_contact(
    phone: str,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
    source: str = "Voice Bot",
) -> dict[str, Any]:
    """
    Create a new GHL contact. Returns the full contact object.
    """
    payload: dict[str, Any] = {
        "phone": _normalize_phone(phone),
        "locationId": settings.GHL_LOCATION_ID,
        "source": source,
        "assignedTo": GHLUsers.DEFAULT_ASSIGNED,
    }
    if first_name:
        payload["firstName"] = first_name
    if last_name:
        payload["lastName"] = last_name
    if email:
        payload["email"] = email

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{GHL_V1}/contacts/", headers=_headers_v1(), json=payload
        )

    _raise_for_status(response, "create_contact")
    data = response.json()
    contact = data.get("contact") or data
    logger.info("GHL contact created", extra={"contact_id": contact.get("id"), "phone": phone})
    return contact


async def lookup_or_create_contact(
    phone: str,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
) -> tuple[dict[str, Any], bool]:
    """
    Look up a contact by phone. If not found, create one.
    Returns (contact_dict, is_new_contact).
    """
    existing = await lookup_contact_by_phone(phone)
    if existing:
        # Update name if we now have it and it was missing
        if first_name and not existing.get("firstName"):
            await update_contact(existing["id"], first_name=first_name, last_name=last_name)
            existing["firstName"] = first_name
            existing["lastName"] = last_name
        return existing, False

    contact = await create_contact(phone, first_name, last_name, email)
    return contact, True


async def update_contact(
    contact_id: str,
    first_name: str = "",
    last_name: str = "",
    email: str = "",
) -> dict[str, Any]:
    """Update basic fields on an existing contact."""
    payload: dict[str, Any] = {}
    if first_name:
        payload["firstName"] = first_name
    if last_name:
        payload["lastName"] = last_name
    if email:
        payload["email"] = email

    if not payload:
        return {}

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.put(
            f"{GHL_V1}/contacts/{contact_id}", headers=_headers_v1(), json=payload
        )
    _raise_for_status(response, "update_contact")
    return response.json().get("contact", {})


async def get_contact(contact_id: str) -> dict[str, Any]:
    """Fetch a contact by ID."""
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            f"{GHL_V1}/contacts/{contact_id}", headers=_headers_v1()
        )
    _raise_for_status(response, "get_contact")
    return response.json().get("contact", response.json())


# ─────────────────────────────────────────────────────────────────────────────
# 2. Qualification Custom Fields
# ─────────────────────────────────────────────────────────────────────────────

async def update_qualification_fields(
    contact_id: str,
    insurance_status: str = "",
    insurance_provider: str = "",
    chief_complaint: str = "",
    referral_source: str = "",
    question_or_concern: str = "",
) -> dict[str, Any]:
    """
    Save lead qualification data to the contact's custom fields.
    Only sends fields that have non-empty values.

    Maps to GHLCustomFields keys defined in config.py.
    """
    custom_fields: list[dict[str, str]] = []

    field_map = {
        GHLCustomFields.INSURANCE_STATUS:   insurance_status,
        GHLCustomFields.INSURANCE_PROVIDER: insurance_provider,
        GHLCustomFields.CHIEF_COMPLAINT:    chief_complaint,
        GHLCustomFields.REFERRAL_SOURCE:    referral_source,
        GHLCustomFields.QUESTION_CONCERN:   question_or_concern,
    }

    for key, value in field_map.items():
        if value:
            custom_fields.append({"key": key, "field_value": value})

    if not custom_fields:
        logger.info("No qualification fields to update", extra={"contact_id": contact_id})
        return {}

    payload = {"customField": custom_fields}

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.put(
            f"{GHL_V1}/contacts/{contact_id}",
            headers=_headers_v1(),
            json=payload,
        )

    _raise_for_status(response, "update_qualification_fields")
    logger.info(
        "Qualification fields updated",
        extra={"contact_id": contact_id, "fields_updated": len(custom_fields)},
    )
    return response.json().get("contact", {})


# ─────────────────────────────────────────────────────────────────────────────
# 3. Pipeline / Opportunity
# ─────────────────────────────────────────────────────────────────────────────

async def create_opportunity(
    contact_id: str,
    name: str,
    stage_id: str = GHLPipeline.Stages.NEW_LEAD,
    monetary_value: float = 0.0,
) -> dict[str, Any]:
    """
    Create a pipeline opportunity in the Voice Bot Pipeline.
    Defaults to the 'New Lead - Voice Bot' stage.
    """
    payload: dict[str, Any] = {
        "pipelineId": GHLPipeline.PIPELINE_ID,
        "locationId": settings.GHL_LOCATION_ID,
        "name": name,
        "contactId": contact_id,
        "pipelineStageId": stage_id,
        "monetaryValue": monetary_value,
        "status": "open",
        "assignedTo": GHLUsers.DEFAULT_ASSIGNED,
    }

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{GHL_V1}/opportunities/", headers=_headers_v1(), json=payload
        )
    _raise_for_status(response, "create_opportunity")
    opp = response.json()
    logger.info(
        "Opportunity created",
        extra={"contact_id": contact_id, "name": name, "stage_id": stage_id},
    )
    return opp


async def get_opportunities_for_contact(contact_id: str) -> list[dict[str, Any]]:
    """
    Fetch all opportunities linked to a contact in the Voice Bot Pipeline.
    Returns a list (may be empty).
    """
    params = {
        "location_id": settings.GHL_LOCATION_ID,
        "contact_id": contact_id,
        "pipeline_id": GHLPipeline.PIPELINE_ID,
    }
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            f"{GHL_V1}/opportunities/search",
            headers=_headers_v1(),
            params=params,
        )

    if response.status_code == 200:
        return response.json().get("opportunities", [])
    logger.warning(
        "Could not fetch opportunities for contact",
        extra={"contact_id": contact_id, "status": response.status_code},
    )
    return []


async def move_opportunity_stage(
    opportunity_id: str,
    stage_id: str,
) -> dict[str, Any]:
    """
    Move an existing opportunity to a new pipeline stage.
    Use GHLPipeline.Stages.* constants for stage_id.
    """
    payload = {"pipelineStageId": stage_id}

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.put(
            f"{GHL_V1}/opportunities/{opportunity_id}",
            headers=_headers_v1(),
            json=payload,
        )
    _raise_for_status(response, "move_opportunity_stage")
    logger.info(
        "Opportunity stage moved",
        extra={"opportunity_id": opportunity_id, "new_stage": stage_id},
    )
    return response.json()


async def ensure_opportunity(
    contact_id: str,
    contact_name: str,
) -> tuple[str, bool]:
    """
    Get the existing open opportunity for this contact, or create one.
    Returns (opportunity_id, is_new).
    """
    existing = await get_opportunities_for_contact(contact_id)
    if existing:
        opp_id = existing[0].get("id", "")
        logger.info("Using existing opportunity", extra={"opportunity_id": opp_id})
        return opp_id, False

    opp_name = f"Voice Bot Lead — {contact_name or 'Unknown'}"
    opp = await create_opportunity(
        contact_id=contact_id,
        name=opp_name,
        stage_id=GHLPipeline.Stages.NEW_LEAD,
    )
    opp_id = opp.get("opportunity", opp).get("id", "")
    return opp_id, True


# ─────────────────────────────────────────────────────────────────────────────
# 4. Notes
# ─────────────────────────────────────────────────────────────────────────────

async def add_note(
    contact_id: str,
    body: str,
    user_id: str = GHLUsers.DEFAULT_ASSIGNED,
) -> dict[str, Any]:
    """Add a note to a GHL contact's timeline."""
    payload: dict[str, Any] = {
        "body": body,
        "contactId": contact_id,
        "userId": user_id,
    }

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{GHL_V1}/contacts/{contact_id}/notes/",
            headers=_headers_v1(),
            json=payload,
        )
    _raise_for_status(response, "add_note")
    logger.info("Note added to contact", extra={"contact_id": contact_id})
    return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Tags
# ─────────────────────────────────────────────────────────────────────────────

async def add_tags(contact_id: str, tags: list[str]) -> dict[str, Any]:
    """Add one or more tags to a GHL contact."""
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{GHL_V1}/contacts/{contact_id}/tags/",
            headers=_headers_v1(),
            json={"tags": tags},
        )
    _raise_for_status(response, "add_tags")
    logger.info("Tags added", extra={"contact_id": contact_id, "tags": tags})
    return response.json()


async def remove_tags(contact_id: str, tags: list[str]) -> dict[str, Any]:
    """Remove one or more tags from a GHL contact."""
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.delete(
            f"{GHL_V1}/contacts/{contact_id}/tags/",
            headers=_headers_v1(),
            json={"tags": tags},
        )
    _raise_for_status(response, "remove_tags")
    logger.info("Tags removed", extra={"contact_id": contact_id, "tags": tags})
    return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# 6. SMS
# ─────────────────────────────────────────────────────────────────────────────

async def send_sms(
    contact_id: str,
    message: str,
    from_number: str = "",
) -> dict[str, Any]:
    """Send an outbound SMS to a contact via GHL Conversations API."""
    payload: dict[str, Any] = {
        "type": "SMS",
        "contactId": contact_id,
        "message": message,
    }
    if from_number:
        payload["fromNumber"] = from_number

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{GHL_V1}/conversations/messages/outbound",
            headers=_headers_v1(),
            json=payload,
        )
    _raise_for_status(response, "send_sms")
    logger.info("SMS sent", extra={"contact_id": contact_id})
    return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Strip non-digit characters and ensure E.164 format (+1XXXXXXXXXX)."""
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}" if digits else phone
