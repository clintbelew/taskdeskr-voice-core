"""
TaskDeskr Voice Core — Tool Dispatcher
=========================================
Receives tool call requests from the LLM and executes the corresponding
GoHighLevel (or system) action.

Each handler:
  - Accepts parsed arguments from the LLM
  - Executes the appropriate service call
  - Returns a result dict that is fed back to the LLM as a tool result message
  - Logs success/failure with call context

The dispatcher is the bridge between the AI's intent and the real world.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.core.config import settings
from src.core.logger import get_logger
from src.services import ghl

logger = get_logger(__name__)


class ToolError(Exception):
    """Raised when a tool execution fails."""


async def dispatch(
    tool_name: str,
    arguments_json: str,
    contact_id: Optional[str],
    phone: Optional[str] = None,
) -> dict[str, Any]:
    """
    Execute a tool requested by the LLM.

    Parameters
    ----------
    tool_name       : Name of the tool (matches a key in TOOL_DEFINITIONS)
    arguments_json  : JSON string of arguments from the LLM
    contact_id      : GHL contact ID for the current caller (may be None)
    phone           : Caller's phone number (used if contact_id is missing)

    Returns
    -------
    Result dict to be returned to the LLM as a tool result.
    Always returns a dict — never raises, so the LLM can handle failures gracefully.
    """
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        logger.error("Invalid tool arguments JSON", extra={"tool": tool_name, "raw": arguments_json})
        return {"success": False, "error": "Invalid arguments format."}

    logger.info("Dispatching tool", extra={"tool": tool_name, "contact_id": contact_id})

    # Ensure we have a contact before attempting CRM operations
    if tool_name not in ("escalate_to_human", "end_call") and not contact_id and phone:
        contact_id = await _ensure_contact(phone)

    try:
        if tool_name == "book_appointment":
            return await _handle_book_appointment(args, contact_id)

        elif tool_name == "add_contact_tag":
            return await _handle_add_tag(args, contact_id)

        elif tool_name == "remove_contact_tag":
            return await _handle_remove_tag(args, contact_id)

        elif tool_name == "add_contact_note":
            return await _handle_add_note(args, contact_id)

        elif tool_name == "send_sms":
            return await _handle_send_sms(args, contact_id)

        elif tool_name == "escalate_to_human":
            return await _handle_escalate(args)

        elif tool_name == "end_call":
            return _handle_end_call(args)

        elif tool_name == "create_opportunity":
            return await _handle_create_opportunity(args, contact_id)

        else:
            logger.warning("Unknown tool requested", extra={"tool": tool_name})
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except ghl.GHLError as exc:
        logger.error(
            "GHL error during tool execution",
            extra={"tool": tool_name, "error": str(exc), "status": exc.status_code},
        )
        return {"success": False, "error": f"CRM action failed: {exc}"}

    except Exception as exc:
        logger.error(
            "Unexpected error during tool execution",
            extra={"tool": tool_name, "error": str(exc)},
            exc_info=True,
        )
        return {"success": False, "error": "An unexpected error occurred. Please try again."}


# ── Individual tool handlers ──────────────────────────────────────────────────

async def _handle_book_appointment(
    args: dict[str, Any], contact_id: Optional[str]
) -> dict[str, Any]:
    if not contact_id:
        return {"success": False, "error": "Cannot book appointment: caller not found in CRM."}

    start_time = args.get("start_time", "")
    if not start_time:
        return {"success": False, "error": "start_time is required to book an appointment."}

    appt = await ghl.book_appointment(
        contact_id=contact_id,
        start_time_iso=start_time,
        title=args.get("title", "Appointment"),
        calendar_id=args.get("calendar_id") or None,
        notes=args.get("notes", ""),
    )
    return {
        "success": True,
        "message": f"Appointment booked for {start_time}.",
        "appointment_id": appt.get("id"),
    }


async def _handle_add_tag(
    args: dict[str, Any], contact_id: Optional[str]
) -> dict[str, Any]:
    if not contact_id:
        return {"success": False, "error": "Cannot add tag: caller not found in CRM."}
    tags = args.get("tags", [])
    if not tags:
        return {"success": False, "error": "No tags provided."}
    await ghl.add_tags(contact_id=contact_id, tags=tags)
    return {"success": True, "message": f"Tags added: {', '.join(tags)}."}


async def _handle_remove_tag(
    args: dict[str, Any], contact_id: Optional[str]
) -> dict[str, Any]:
    if not contact_id:
        return {"success": False, "error": "Cannot remove tag: caller not found in CRM."}
    tags = args.get("tags", [])
    if not tags:
        return {"success": False, "error": "No tags provided."}
    await ghl.remove_tags(contact_id=contact_id, tags=tags)
    return {"success": True, "message": f"Tags removed: {', '.join(tags)}."}


async def _handle_add_note(
    args: dict[str, Any], contact_id: Optional[str]
) -> dict[str, Any]:
    if not contact_id:
        return {"success": False, "error": "Cannot add note: caller not found in CRM."}
    note_text = args.get("note", "").strip()
    if not note_text:
        return {"success": False, "error": "Note text is empty."}
    await ghl.add_note(contact_id=contact_id, body=note_text)
    return {"success": True, "message": "Note added to contact record."}


async def _handle_send_sms(
    args: dict[str, Any], contact_id: Optional[str]
) -> dict[str, Any]:
    if not contact_id:
        return {"success": False, "error": "Cannot send SMS: caller not found in CRM."}
    message = args.get("message", "").strip()
    if not message:
        return {"success": False, "error": "SMS message is empty."}
    await ghl.send_sms(contact_id=contact_id, message=message)
    return {"success": True, "message": "SMS sent successfully."}


async def _handle_escalate(args: dict[str, Any]) -> dict[str, Any]:
    reason = args.get("reason", "Caller requested human assistance.")
    transfer_number = settings.ESCALATION_PHONE_NUMBER
    if not transfer_number:
        logger.warning("Escalation requested but ESCALATION_PHONE_NUMBER is not set.")
        return {
            "success": False,
            "error": "Escalation phone number not configured.",
            "action": "escalate",
        }
    logger.info("Escalating call to human", extra={"reason": reason, "transfer_to": transfer_number})
    return {
        "success": True,
        "action": "transfer",
        "transfer_to": transfer_number,
        "reason": reason,
        "message": "Transferring you to a team member now. Please hold.",
    }


def _handle_end_call(args: dict[str, Any]) -> dict[str, Any]:
    farewell = args.get("farewell_message", "Thank you for calling. Have a great day!")
    return {
        "success": True,
        "action": "end_call",
        "farewell_message": farewell,
    }


async def _handle_create_opportunity(
    args: dict[str, Any], contact_id: Optional[str]
) -> dict[str, Any]:
    if not contact_id:
        return {"success": False, "error": "Cannot create opportunity: caller not found in CRM."}
    name = args.get("name", "").strip()
    if not name:
        return {"success": False, "error": "Opportunity name is required."}
    opp = await ghl.create_opportunity(
        contact_id=contact_id,
        name=name,
        monetary_value=float(args.get("monetary_value", 0)),
        stage_id=args.get("stage_id", ""),
    )
    return {
        "success": True,
        "message": f"Opportunity '{name}' created.",
        "opportunity_id": opp.get("id"),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _ensure_contact(phone: str) -> Optional[str]:
    """Look up or create a contact by phone and return the contact ID."""
    try:
        contact = await ghl.lookup_contact_by_phone(phone)
        if contact:
            return contact.get("id")
        # Auto-create a minimal contact record for unknown callers
        new_contact = await ghl.upsert_contact(phone=phone)
        return new_contact.get("id")
    except ghl.GHLError as exc:
        logger.error("Failed to ensure contact", extra={"phone": phone, "error": str(exc)})
        return None
