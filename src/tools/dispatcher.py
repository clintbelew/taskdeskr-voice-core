"""
TaskDeskr Voice Core — Tool Dispatcher
========================================
Executes tool calls requested by the LLM during a live Vapi conversation.

Each handler:
  - Receives the parsed arguments from the LLM
  - Reads call state (contact_id, opportunity_id, etc.) from the call store
  - Executes the appropriate GHL API operation(s)
  - Returns a result string the LLM reads or uses to continue reasoning
  - Never raises — all errors are caught and returned as graceful messages

Tool handlers:
  save_caller_info        → update contact name/email in GHL + tag
  save_lead_info          → write lead qualification fields to GHL contact
  create_lead_opportunity → create opportunity in Voice Bot Pipeline
  send_website_link       → SMS taskdeskr.com to the caller
  send_demo_booking_link  → SMS the demo calendar booking link to the caller
  end_call                → signal Vapi to end the call
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.core.config import GHLPipeline
from src.core.logger import get_logger
from src.services import ghl

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SMS Link Constants
# ─────────────────────────────────────────────────────────────────────────────

TASKDESKR_WEBSITE_URL    = "https://taskdeskr.com"
DEMO_BOOKING_LINK_URL    = "https://api.leadconnectorhq.com/widget/booking/AewaSaTHTTYUBFqFJ9Yg"


async def dispatch(
    tool_name: str,
    arguments_json: str,
    contact_id: Optional[str],
    phone: Optional[str] = None,
    call_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Route a tool call from the LLM to the correct handler.

    Parameters
    ----------
    tool_name       : Name of the tool as defined in definitions.py
    arguments_json  : JSON string of arguments from the LLM
    contact_id      : GHL contact ID for the current caller
    phone           : Caller phone number (fallback if contact_id missing)
    call_state      : Mutable dict holding call-scoped data

    Returns
    -------
    dict with keys:
      result  : str  — message the LLM receives as the tool result
      action  : dict — optional Vapi action (e.g. {"type": "end-call"})
    """
    if call_state is None:
        call_state = {}

    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        logger.error("Invalid tool arguments JSON", extra={"tool": tool_name})
        return {"result": "I had trouble reading that request. Please continue."}

    logger.info("Dispatching tool", extra={"tool": tool_name, "contact_id": contact_id})

    # Auto-resolve contact if we have a phone but no contact_id yet
    if not contact_id and phone and tool_name not in ("end_call",):
        contact_id = await _resolve_contact_id(phone)
        if contact_id:
            call_state["contact_id"] = contact_id

    # Inject resolved contact_id into call_state for handlers
    if contact_id and not call_state.get("contact_id"):
        call_state["contact_id"] = contact_id

    handlers = {
        "save_caller_info":        _handle_save_caller_info,
        "save_lead_info":          _handle_save_lead_info,
        "create_lead_opportunity": _handle_create_lead_opportunity,
        "send_website_link":       _handle_send_website_link,
        "send_demo_booking_link":  _handle_send_demo_booking_link,
        "end_call":                _handle_end_call,
    }

    handler = handlers.get(tool_name)
    if not handler:
        logger.warning("Unknown tool called", extra={"tool": tool_name})
        return {"result": f"I don't know how to handle '{tool_name}'. Continuing the conversation."}

    try:
        return await handler(args, call_state)
    except ghl.GHLError as exc:
        logger.error(
            "GHL error in tool handler",
            extra={"tool": tool_name, "error": str(exc), "status": exc.status_code},
        )
        return {
            "result": (
                "I wasn't able to save that information right now, but I've noted it. "
                "Please continue."
            )
        }
    except Exception:
        logger.exception("Unexpected error in tool handler", extra={"tool": tool_name})
        return {"result": "Something went wrong on my end. Let me continue helping you."}


# ─────────────────────────────────────────────────────────────────────────────
# Tool Handlers
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_save_caller_info(
    args: dict[str, Any],
    call_state: dict[str, Any],
) -> dict[str, Any]:
    """Update the contact's name and email in GHL. Tag as voice-bot-lead."""
    contact_id = call_state.get("contact_id")
    if not contact_id:
        return {"result": "I'll note your name for the summary."}

    first_name = args.get("first_name", "")
    last_name  = args.get("last_name", "")
    email      = args.get("email", "")

    await ghl.update_contact(contact_id, first_name=first_name, last_name=last_name, email=email)

    # Mirror in call state for the end-of-call summary
    call_state["caller_first_name"] = first_name
    call_state["caller_last_name"]  = last_name
    if email:
        call_state["caller_email"] = email

    # Tag as voice-bot-lead (GHL ignores duplicate tags)
    await ghl.add_tags(contact_id, ["voice-bot-lead"])

    logger.info("Caller info saved", extra={"contact_id": contact_id, "first_name": first_name})
    return {"result": f"Got it — I've saved {first_name}'s information."}


async def _handle_save_lead_info(
    args: dict[str, Any],
    call_state: dict[str, Any],
) -> dict[str, Any]:
    """Write TaskDeskr lead qualification fields to the GHL contact."""
    contact_id = call_state.get("contact_id")
    if not contact_id:
        return {"result": "I've noted the information for the call summary."}

    # Build custom field updates — only fields that were actually collected
    field_updates: dict[str, str] = {}

    if args.get("interest_level"):
        field_updates["interest_level"] = args["interest_level"]
    if args.get("business_type"):
        field_updates["business_type"] = args["business_type"]
    if args.get("main_question"):
        field_updates["main_question"] = args["main_question"]
    if args.get("referral_source"):
        field_updates["referral_source"] = args["referral_source"]
    if "demo_requested" in args:
        field_updates["demo_requested"] = str(args["demo_requested"])

    if field_updates:
        try:
            await ghl.update_contact_fields(contact_id, field_updates)
        except Exception:
            logger.warning("Could not update GHL custom fields for lead info", extra={"contact_id": contact_id})

    # Add tags based on interest
    tags_to_add = ["taskdeskr-inquiry"]
    if args.get("demo_requested"):
        tags_to_add.append("demo-requested")
    if args.get("interest_level") == "high":
        tags_to_add.append("hot-lead")

    await ghl.add_tags(contact_id, tags_to_add)

    # Mirror in call state for summary
    call_state.setdefault("lead_info", {}).update({k: v for k, v in args.items() if v})

    logger.info("Lead info saved", extra={"contact_id": contact_id, "fields": list(field_updates.keys())})
    return {"result": "Lead information saved."}


async def _handle_create_lead_opportunity(
    args: dict[str, Any],
    call_state: dict[str, Any],
) -> dict[str, Any]:
    """Create an opportunity in the Voice Bot Pipeline at the New Lead stage."""
    contact_id = call_state.get("contact_id")
    if not contact_id:
        return {"result": "Unable to create opportunity — contact not found."}

    # Prevent duplicate opportunities per call
    if call_state.get("opportunity_id"):
        return {"result": "Lead opportunity already created for this caller."}

    opp_name = args.get("opportunity_name") or (
        f"TaskDeskr Lead — "
        f"{call_state.get('caller_first_name', 'Unknown')} "
        f"{call_state.get('caller_last_name', '')}".strip()
    )

    opp_id, is_new = await ghl.ensure_opportunity(
        contact_id=contact_id,
        contact_name=opp_name,
    )

    call_state["opportunity_id"]   = opp_id
    call_state["opportunity_name"] = opp_name

    logger.info("Lead opportunity ready", extra={"opportunity_id": opp_id, "is_new": is_new})

    return {
        "result": (
            "Lead opportunity created in the Voice Bot Pipeline."
            if is_new else
            "Existing opportunity linked."
        )
    }


async def _handle_send_website_link(
    args: dict[str, Any],
    call_state: dict[str, Any],
) -> dict[str, Any]:
    """Send the TaskDeskr website link via SMS and move opportunity stage."""
    contact_id     = call_state.get("contact_id")
    opportunity_id = call_state.get("opportunity_id")

    # Create opportunity first if it doesn't exist yet
    if not opportunity_id and contact_id:
        contact_name = (
            f"{call_state.get('caller_first_name', '')} "
            f"{call_state.get('caller_last_name', '')}".strip() or "Unknown"
        )
        opp_id, _ = await ghl.ensure_opportunity(contact_id, f"TaskDeskr Lead — {contact_name}")
        opportunity_id = opp_id
        call_state["opportunity_id"] = opp_id

    if opportunity_id:
        try:
            await ghl.move_opportunity_stage(
                opportunity_id=opportunity_id,
                stage_id=GHLPipeline.Stages.BOOKING_LINK_SENT,
            )
        except Exception:
            logger.warning("Could not move opportunity stage", extra={"opportunity_id": opportunity_id})
        call_state["pipeline_stage"] = "website_link_sent"

    # Send the SMS
    sms_sent = False
    if contact_id:
        first_name = call_state.get("caller_first_name", "").strip()
        greeting   = f"Hi {first_name}! " if first_name else "Hi! "
        sms_body   = (
            f"{greeting}Here's the TaskDeskr website: {TASKDESKR_WEBSITE_URL} — "
            f"AI-powered business operations that replaces hiring front desk staff. "
            f"Reply STOP to opt out."
        )
        try:
            await ghl.send_sms(contact_id=contact_id, message=sms_body)
            sms_sent = True
            logger.info("Website link SMS sent", extra={"contact_id": contact_id})
        except ghl.GHLError as exc:
            logger.error("Failed to send website link SMS", extra={"contact_id": contact_id, "error": str(exc)})

    if sms_sent:
        return {
            "result": (
                f"Website link sent via text message to the caller. "
                f"Tell the caller: 'I just texted you the website — taskdeskr.com. "
                f"Feel free to check it out whenever you get a chance!'"
            )
        }
    return {
        "result": (
            "Could not send SMS — tell the caller the website is taskdeskr.com "
            "and they can visit it anytime."
        )
    }


async def _handle_send_demo_booking_link(
    args: dict[str, Any],
    call_state: dict[str, Any],
) -> dict[str, Any]:
    """Send the demo booking calendar link via SMS and move opportunity stage."""
    contact_id     = call_state.get("contact_id")
    opportunity_id = call_state.get("opportunity_id")

    # Create opportunity first if it doesn't exist yet
    if not opportunity_id and contact_id:
        contact_name = (
            f"{call_state.get('caller_first_name', '')} "
            f"{call_state.get('caller_last_name', '')}".strip() or "Unknown"
        )
        opp_id, _ = await ghl.ensure_opportunity(contact_id, f"TaskDeskr Lead — {contact_name}")
        opportunity_id = opp_id
        call_state["opportunity_id"] = opp_id

    if opportunity_id:
        try:
            await ghl.move_opportunity_stage(
                opportunity_id=opportunity_id,
                stage_id=GHLPipeline.Stages.BOOKING_LINK_SENT,
            )
        except Exception:
            logger.warning("Could not move opportunity stage", extra={"opportunity_id": opportunity_id})
        call_state["pipeline_stage"]         = "demo_booking_sent"
        call_state["booking_link_requested"] = True

    # Send the SMS
    sms_sent = False
    if contact_id:
        first_name    = call_state.get("caller_first_name", "").strip()
        preferred_time = args.get("preferred_time", "")
        greeting      = f"Hi {first_name}! " if first_name else "Hi! "
        time_note     = f" (you mentioned {preferred_time} works for you)" if preferred_time else ""
        sms_body      = (
            f"{greeting}Here's the link to book your TaskDeskr demo call{time_note}: "
            f"{DEMO_BOOKING_LINK_URL} — Pick a time that works for you and our team will walk you through everything. "
            f"Reply STOP to opt out."
        )
        try:
            await ghl.send_sms(contact_id=contact_id, message=sms_body)
            sms_sent = True
            logger.info("Demo booking link SMS sent", extra={"contact_id": contact_id})
        except ghl.GHLError as exc:
            logger.error("Failed to send demo booking SMS", extra={"contact_id": contact_id, "error": str(exc)})

    if sms_sent:
        return {
            "result": (
                "Demo booking link sent via text message. "
                "Tell the caller: 'I just texted you the booking link — pick a time that works for you "
                "and our team will walk you through everything on the demo call!'"
            )
        }
    return {
        "result": (
            "Could not send SMS — tell the caller they can book a demo at "
            f"{DEMO_BOOKING_LINK_URL}"
        )
    }


async def _handle_end_call(
    args: dict[str, Any],
    call_state: dict[str, Any],
) -> dict[str, Any]:
    """Signal Vapi to end the call."""
    reason = args.get("reason", "completed")
    call_state["end_reason"] = reason
    logger.info("End call requested by LLM", extra={"reason": reason})
    return {
        "result": "Thank you for calling TaskDeskr. Have a great day!",
        "action": {"type": "end-call"},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _resolve_contact_id(phone: str) -> Optional[str]:
    """Look up or create a contact by phone and return the contact ID."""
    try:
        contact = await ghl.lookup_contact_by_phone(phone)
        if contact:
            return contact.get("id")
        new_contact = await ghl.create_contact(phone=phone)
        return new_contact.get("id")
    except ghl.GHLError as exc:
        logger.error("Failed to resolve contact", extra={"phone": phone, "error": str(exc)})
        return None
