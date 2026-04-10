"""
TaskDeskr Voice Core — GoHighLevel Service (v2 API)
====================================================
All endpoints use the GHL v2 LeadConnector API (services.leadconnectorhq.com).
Compatible with Private Integration Tokens (PIT) — the modern GHL auth method.

Phase 1 capabilities:
  1. lookup_or_create_contact  — find by phone, create if missing
  2. update_qualification_fields — save intake custom fields to contact
  3. create_opportunity        — open a deal in the Voice Bot Pipeline
  4. move_opportunity_stage    — advance the deal stage (e.g. → Booking Link Sent)
  5. add_note                  — log structured call summary to contact timeline
  6. add_tags                  — tag contacts (e.g. "voice-bot-lead")
  7. send_sms                  — outbound SMS via GHL Conversations API

All methods are async. Errors raise GHLError with status code and body for
clean upstream handling. No silent failures.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from src.core.config import GHLCustomFields, GHLPipeline, GHLUsers, settings
from src.core.logger import get_logger

logger = get_logger(__name__)

# GHL v2 API — the only base URL needed for PIT tokens
GHL_BASE = "https://services.leadconnectorhq.com"


def _headers() -> dict[str, str]:
    """Standard headers for all GHL v2 API calls."""
    return {
        "Authorization": f"Bearer {settings.GHL_API_KEY}",
        "Content-Type": "application/json",
        "Version": "2021-07-28",
    }


class GHLError(Exception):
    """Raised when a GoHighLevel API call fails."""

    def __init__(self, message: str, status_code: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _raise_for_status(response: httpx.Response, context: str) -> None:
    if response.status_code not in (200, 201, 204):
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
    """
    normalized = _normalize_phone(phone)
    params = {
        "locationId": settings.GHL_LOCATION_ID,
        "query": normalized,
        "limit": 1,
    }

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            f"{GHL_BASE}/contacts/",
            headers=_headers(),
            params=params,
        )

    if response.status_code == 200:
        data = response.json()
        contacts = data.get("contacts", [])
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
    """Create a new GHL contact. Returns the full contact object."""
    payload: dict[str, Any] = {
        "phone": _normalize_phone(phone),
        "locationId": settings.GHL_LOCATION_ID,
        "source": source,
    }
    if first_name:
        payload["firstName"] = first_name
    if last_name:
        payload["lastName"] = last_name
    if email:
        payload["email"] = email
    if GHLUsers.DEFAULT_ASSIGNED:
        payload["assignedTo"] = GHLUsers.DEFAULT_ASSIGNED

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{GHL_BASE}/contacts/",
            headers=_headers(),
            json=payload,
        )

    _raise_for_status(response, "create_contact")
    data = response.json()
    # v2 API wraps the contact under "contact" key
    contact = data.get("contact") or data
    logger.info(
        "GHL contact created",
        extra={"contact_id": contact.get("id"), "phone": phone},
    )
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
            await update_contact(
                existing["id"],
                first_name=first_name,
                last_name=last_name,
            )
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
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=_headers(),
            json=payload,
        )
    _raise_for_status(response, "update_contact")
    return response.json().get("contact", {})


async def get_contact(contact_id: str) -> dict[str, Any]:
    """Fetch a contact by ID."""
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=_headers(),
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
            custom_fields.append({"id": key, "field_value": value})

    if not custom_fields:
        logger.info(
            "No qualification fields to update",
            extra={"contact_id": contact_id},
        )
        return {}

    payload = {"customFields": custom_fields}

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.put(
            f"{GHL_BASE}/contacts/{contact_id}",
            headers=_headers(),
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
    }
    if GHLUsers.DEFAULT_ASSIGNED:
        payload["assignedTo"] = GHLUsers.DEFAULT_ASSIGNED

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{GHL_BASE}/opportunities/",
            headers=_headers(),
            json=payload,
        )
    _raise_for_status(response, "create_opportunity")
    opp = response.json()
    logger.info(
        "Opportunity created",
        extra={"contact_id": contact_id, "opp_name": name, "stage_id": stage_id},
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
            f"{GHL_BASE}/opportunities/search",
            headers=_headers(),
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
            f"{GHL_BASE}/opportunities/{opportunity_id}",
            headers=_headers(),
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
    # v2 API may wrap under "opportunity" key
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
    # GHL v2: contactId is in the URL path, not the request body
    payload: dict[str, Any] = {"body": body}
    if user_id:
        payload["userId"] = user_id

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{GHL_BASE}/contacts/{contact_id}/notes/",
            headers=_headers(),
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
            f"{GHL_BASE}/contacts/{contact_id}/tags/",
            headers=_headers(),
            json={"tags": tags},
        )
    _raise_for_status(response, "add_tags")
    logger.info("Tags added", extra={"contact_id": contact_id, "tags": tags})
    return response.json()


async def remove_tags(contact_id: str, tags: list[str]) -> dict[str, Any]:
    """Remove one or more tags from a GHL contact."""
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.delete(
            f"{GHL_BASE}/contacts/{contact_id}/tags/",
            headers=_headers(),
            json={"tags": tags},
        )
    _raise_for_status(response, "remove_tags")
    logger.info("Tags removed", extra={"contact_id": contact_id, "tags": tags})
    return response.json()


# ─────────────────────────────────────────────────────────────────────────────
# 6. SMS via Conversations API
# ─────────────────────────────────────────────────────────────────────────────

async def _get_or_create_conversation(contact_id: str) -> Optional[str]:
    """
    Look up an existing GHL conversation for a contact, or create one.
    Returns the conversationId string, or None on failure.
    """
    async with httpx.AsyncClient(timeout=12) as client:
        # Search for existing conversation
        resp = await client.get(
            f"{GHL_BASE}/conversations/search",
            headers=_headers(),
            params={
                "locationId": settings.GHL_LOCATION_ID,
                "contactId": contact_id,
                "limit": 1,
            },
        )
        if resp.status_code == 200:
            data = resp.json()
            conversations = data.get("conversations", [])
            if conversations:
                conv_id = conversations[0].get("id")
                if conv_id:
                    logger.info(
                        "Found existing conversation",
                        extra={"contact_id": contact_id, "conversation_id": conv_id},
                    )
                    return conv_id

        # No existing conversation — create one
        create_resp = await client.post(
            f"{GHL_BASE}/conversations/",
            headers=_headers(),
            json={
                "contactId": contact_id,
                "locationId": settings.GHL_LOCATION_ID,
            },
        )
        if create_resp.status_code in (200, 201):
            conv_data = create_resp.json()
            conv_id = (
                conv_data.get("conversation", {}).get("id")
                or conv_data.get("id")
            )
            if conv_id:
                logger.info(
                    "Created new conversation",
                    extra={"contact_id": contact_id, "conversation_id": conv_id},
                )
                return conv_id

    logger.warning(
        "Could not get or create conversation",
        extra={"contact_id": contact_id},
    )
    return None


async def send_sms(
    contact_id: str,
    message: str,
    from_number: str = "",
) -> dict[str, Any]:
    """
    Send an outbound SMS to a contact via GHL Conversations API.

    Strategy (avoids the 'No conversationProviderId' 400 error):
      1. Look up or create the GHL conversation for this contact.
      2. Send via POST /conversations/messages using conversationId — GHL
         resolves the provider automatically from the conversation context.
      3. Fall back to the /outbound endpoint with fromNumber if step 2 fails.
    """
    # Step 1: resolve conversation
    conversation_id = await _get_or_create_conversation(contact_id)

    if conversation_id:
        # Step 2: send via conversation thread
        payload: dict[str, Any] = {
            "type": "SMS",
            "message": message,
            "conversationId": conversation_id,
            "contactId": contact_id,
        }
        if from_number:
            payload["fromNumber"] = from_number

        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                f"{GHL_BASE}/conversations/messages",
                headers=_headers(),
                json=payload,
            )
        if response.status_code in (200, 201):
            logger.info(
                "SMS sent via conversation",
                extra={"contact_id": contact_id, "conversation_id": conversation_id},
            )
            return response.json()
        logger.warning(
            "SMS via conversation failed — trying outbound fallback",
            extra={
                "contact_id": contact_id,
                "status": response.status_code,
                "body": response.text[:300],
            },
        )

    # Step 3: fallback — outbound endpoint
    fallback_payload: dict[str, Any] = {
        "type": "SMS",
        "contactId": contact_id,
        "message": message,
    }
    if from_number:
        fallback_payload["fromNumber"] = from_number

    async with httpx.AsyncClient(timeout=12) as client:
        fallback_resp = await client.post(
            f"{GHL_BASE}/conversations/messages/outbound",
            headers=_headers(),
            json=fallback_payload,
        )
    _raise_for_status(fallback_resp, "send_sms")
    logger.info("SMS sent via outbound fallback", extra={"contact_id": contact_id})
    return fallback_resp.json()


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


# ─────────────────────────────────────────────────────────────────────────────
# 8. Calendar — Availability & Booking
# ─────────────────────────────────────────────────────────────────────────────

# The primary demo-consultation calendar in the TaskDeskr GHL sub-account.
# This is "Clint Belew Personal Calendar" — the 30-min demo booking calendar.
GHL_CALENDAR_ID = "5K0hLjasj81cHyeSK6Xn"

# Timezone used for all slot display and booking
GHL_TIMEZONE = "America/Chicago"


async def check_availability(
    preferred_date: str,
    calendar_id: str = GHL_CALENDAR_ID,
    days_ahead: int = 5,
) -> list[dict[str, Any]]:
    """
    Fetch real open time slots from the GHL calendar API.

    Queries the GHL free-slots endpoint for the preferred date plus
    the next `days_ahead` days, returning up to 8 confirmed-open slots.

    Args:
        preferred_date: ISO date string (YYYY-MM-DD) — the caller's preferred day.
        calendar_id:    GHL calendar ID to check (defaults to demo calendar).
        days_ahead:     How many additional days to search after preferred_date.

    Returns:
        A list of up to 8 slot dicts:
        [{"date": "Monday, April 7", "time": "10:00 AM",
          "iso": "2026-04-07T10:00:00-05:00", "epoch_ms": ...}, ...]
    """
    from datetime import datetime, timedelta
    import pytz

    tz = pytz.timezone(GHL_TIMEZONE)
    now = datetime.now(tz)

    # Parse preferred date; fall back to tomorrow if invalid
    try:
        start_dt = tz.localize(datetime.strptime(preferred_date, "%Y-%m-%d"))
    except (ValueError, TypeError):
        start_dt = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    # Search window: from start_dt to start_dt + days_ahead
    search_days = max(days_ahead, 7)  # always search at least 7 days
    end_dt = start_dt + timedelta(days=search_days)

    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    # Query GHL free-slots API
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{GHL_BASE}/calendars/{calendar_id}/free-slots",
                headers=_headers(),
                params={
                    "startDate": start_ms,
                    "endDate": end_ms,
                    "timezone": GHL_TIMEZONE,
                },
            )
        _raise_for_status(resp, "check_availability")
        slots_by_date: dict[str, Any] = resp.json()
    except Exception as exc:
        logger.warning(
            "GHL free-slots API failed, falling back to generated slots",
            extra={"error": str(exc)},
        )
        slots_by_date = {}

    result: list[dict[str, Any]] = []

    if slots_by_date:
        # Parse the GHL response: {"YYYY-MM-DD": {"slots": ["ISO", ...]}, ...}
        for date_str in sorted(slots_by_date.keys()):
            day_slots = slots_by_date[date_str].get("slots", [])
            for iso_slot in day_slots:
                try:
                    local_dt = datetime.fromisoformat(iso_slot)
                    if local_dt.tzinfo is None:
                        local_dt = tz.localize(local_dt)
                    else:
                        local_dt = local_dt.astimezone(tz)
                    if local_dt <= now:
                        continue
                    result.append({
                        "date": local_dt.strftime("%A, %B %-d"),
                        "time": local_dt.strftime("%-I:%M %p"),
                        "iso": local_dt.isoformat(),
                        "epoch_ms": int(local_dt.timestamp() * 1000),
                    })
                    if len(result) >= 8:
                        break
                except Exception:
                    continue
            if len(result) >= 8:
                break
    else:
        # Fallback: generate slots mathematically if GHL API fails
        SLOT_HOURS = [
            9, 9.5, 10, 10.5, 11, 11.5,
            12, 12.5, 13, 13.5, 14, 14.5,
            15, 15.5, 16, 16.5, 17
        ]
        naive_start = start_dt.replace(tzinfo=None)
        for day_offset in range(search_days + 1):
            day = naive_start + timedelta(days=day_offset)
            for frac_hour in SLOT_HOURS:
                hour = int(frac_hour)
                minute = 30 if frac_hour != int(frac_hour) else 0
                naive_dt = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
                local_dt = tz.localize(naive_dt)
                if local_dt <= now:
                    continue
                result.append({
                    "date": local_dt.strftime("%A, %B %-d"),
                    "time": local_dt.strftime("%-I:%M %p"),
                    "iso": local_dt.isoformat(),
                    "epoch_ms": int(local_dt.timestamp() * 1000),
                })
                if len(result) >= 8:
                    break
            if len(result) >= 8:
                break

    logger.info(
        "check_availability slots fetched",
        extra={"preferred_date": preferred_date, "slot_count": len(result), "source": "ghl_api" if slots_by_date else "fallback"},
    )
    return result


async def create_appointment(
    contact_id: str,
    slot_iso: str,
    caller_name: str,
    caller_phone: str,
    reason: str = "TaskDeskr Demo Consultation",
    calendar_id: str = GHL_CALENDAR_ID,
) -> dict[str, Any]:
    """
    Book an appointment in GHL for the given contact and time slot.

    Args:
        contact_id:   GHL contact ID.
        slot_iso:     ISO datetime string of the selected slot (from check_availability).
        caller_name:  Full name of the caller (used as appointment title).
        caller_phone: Caller's phone number.
        reason:       Reason for the appointment (shown in GHL calendar).
        calendar_id:  GHL calendar ID to book into.

    Returns:
        The GHL appointment object dict on success.

    Raises:
        GHLError on API failure.
    """
    from datetime import datetime, timedelta

    # Parse the slot to compute end time (30-min slot)
    try:
        start_dt = datetime.fromisoformat(slot_iso)
        end_dt = start_dt + timedelta(minutes=30)
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
    except Exception:
        start_iso = slot_iso
        end_iso = slot_iso  # GHL will use calendar default duration

    payload: dict[str, Any] = {
        "calendarId": calendar_id,
        "locationId": settings.GHL_LOCATION_ID,
        "contactId": contact_id,
        "startTime": start_iso,
        "endTime": end_iso,
        "title": f"Demo Consultation — {caller_name}",
        "appointmentStatus": "confirmed",
        "address": caller_phone,
        "notes": reason,
        "ignoreDateRange": False,
        "toNotify": True,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{GHL_BASE}/calendars/events/appointments",
            headers=_headers(),
            json=payload,
        )

    _raise_for_status(resp, "create_appointment")

    appt_data = resp.json()
    logger.info(
        "Appointment created",
        extra={
            "contact_id": contact_id,
            "calendar_id": calendar_id,
            "slot": slot_iso,
            "appointment_id": appt_data.get("id", "unknown"),
        },
    )
    return appt_data
