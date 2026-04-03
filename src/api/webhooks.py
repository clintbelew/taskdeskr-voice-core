"""
TaskDeskr Voice Core — Vapi Webhook Handler
=============================================
Processes all inbound webhook events from Vapi.

Vapi sends events to your server URL for:
  - assistant-request   : Vapi needs to know which assistant config to use
  - call-started        : A new call has begun
  - transcript          : Real-time transcript chunks
  - function-call       : LLM has requested a tool execution
  - end-of-call-report  : Call has ended, full transcript available
  - hang                : Caller hung up

Each handler is a pure async function that receives the parsed payload
and returns a response dict (serialized to JSON by the route layer).

Reference: https://docs.vapi.ai/server-url
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

from src.core.config import settings
from src.core.logger import get_logger, set_call_context, clear_call_context
from src.services import context as ctx_service
from src.services import summary as summary_service
from src.tools import dispatcher
from src.tools.definitions import TOOL_DEFINITIONS

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# In-memory call state store
# Maps call_id → mutable state dict shared across all handlers for that call
# Replace with Redis for multi-instance / multi-worker deployments
# ─────────────────────────────────────────────────────────────────────────────
_call_state: dict[str, dict[str, Any]] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Signature verification
# ─────────────────────────────────────────────────────────────────────────────

def verify_vapi_signature(payload_bytes: bytes, signature_header: str) -> bool:
    """
    Verify the HMAC-SHA256 signature Vapi sends with each webhook.
    Returns True if valid or if VAPI_WEBHOOK_SECRET is not configured.
    """
    secret = settings.VAPI_WEBHOOK_SECRET
    if not secret:
        logger.warning("VAPI_WEBHOOK_SECRET not set — skipping signature verification")
        return True

    expected = hmac.new(
        secret.encode(), payload_bytes, digestmod=hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


# ─────────────────────────────────────────────────────────────────────────────
# Main dispatcher
# ─────────────────────────────────────────────────────────────────────────────

async def handle_vapi_event(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Route an inbound Vapi event to the appropriate handler.
    Returns a response dict that Vapi expects for each event type.
    """
    message    = payload.get("message", payload)
    event_type = message.get("type", "")
    call       = message.get("call", {})
    call_id    = call.get("id", message.get("call_id", "unknown"))

    phone = _extract_phone(call)
    set_call_context(call_id=call_id, phone=phone)

    logger.info("Vapi event received", extra={"event_type": event_type})

    try:
        if event_type == "assistant-request":
            return await _handle_assistant_request(message, call_id, phone)

        elif event_type == "call-started":
            return await _handle_call_started(message, call_id, phone)

        elif event_type == "function-call":
            return await _handle_function_call(message, call_id)

        elif event_type == "end-of-call-report":
            return await _handle_end_of_call(message, call_id)

        elif event_type == "transcript":
            return _handle_transcript(message, call_id)

        elif event_type == "hang":
            return _handle_hang(call_id)

        else:
            logger.info("Unhandled Vapi event type", extra={"event_type": event_type})
            return {"status": "ignored", "event_type": event_type}

    except Exception as exc:
        logger.error(
            "Unhandled exception in webhook handler",
            extra={"event_type": event_type, "error": str(exc)},
            exc_info=True,
        )
        return {"error": "Internal server error", "event_type": event_type}

    finally:
        clear_call_context()


# ─────────────────────────────────────────────────────────────────────────────
# Event Handlers
# ─────────────────────────────────────────────────────────────────────────────

async def _handle_assistant_request(
    message: dict[str, Any],
    call_id: str,
    phone: Optional[str],
) -> dict[str, Any]:
    """
    Vapi calls this when it needs the assistant configuration.
    We return a dynamic assistant config with a context-enriched system prompt.
    """
    logger.info("Handling assistant-request")

    system_prompt, contact = await ctx_service.build_context(phone=phone or "")

    contact_id = contact.get("id") if contact else None

    # Initialize call state — this dict is shared across all handlers for this call
    _call_state[call_id] = {
        "system_prompt":  system_prompt,
        "contact":        contact,
        "contact_id":     contact_id,
        "phone":          phone,
        "transcript":     [],
        "messages":       [],
        # Phase 1 tracking fields
        "caller_first_name":       contact.get("firstName", "") if contact else "",
        "caller_last_name":        contact.get("lastName", "")  if contact else "",
        "caller_email":            contact.get("email", "")     if contact else "",
        "opportunity_id":          None,
        "opportunity_name":        None,
        "pipeline_stage":          "new_lead",
        "booking_link_requested":  False,
        "qualification":           {},
        "end_reason":              None,
    }

    return {
        "assistant": {
            "name": "Aria — TaskDeskr AI Front Desk",
            "model": {
                "provider": "openai",
                "model": settings.OPENAI_MODEL,
                "systemPrompt": system_prompt,
                "tools": TOOL_DEFINITIONS,
                "temperature": 0.4,
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "rachel",
            },
            "firstMessage": _build_greeting(contact),
            "endCallMessage": "Thank you for calling TaskDeskr. Have a wonderful day!",
            "endCallPhrases": [
                "goodbye", "bye bye", "talk later", "have a good day", "thank you bye"
            ],
            "recordingEnabled": True,
            "maxDurationSeconds": 600,
            "silenceTimeoutSeconds": 30,
            "responseDelaySeconds": 0.5,
            "numWordsToInterruptAssistant": 3,
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-2",
                "language": "en-US",
            },
        }
    }


async def _handle_call_started(
    message: dict[str, Any],
    call_id: str,
    phone: Optional[str],
) -> dict[str, Any]:
    """Initialize call state if not already done via assistant-request."""
    if call_id not in _call_state:
        system_prompt, contact = await ctx_service.build_context(phone=phone or "")
        contact_id = contact.get("id") if contact else None
        _call_state[call_id] = {
            "system_prompt":  system_prompt,
            "contact":        contact,
            "contact_id":     contact_id,
            "phone":          phone,
            "transcript":     [],
            "messages":       [],
            "caller_first_name":       contact.get("firstName", "") if contact else "",
            "caller_last_name":        contact.get("lastName", "")  if contact else "",
            "caller_email":            contact.get("email", "")     if contact else "",
            "opportunity_id":          None,
            "opportunity_name":        None,
            "pipeline_stage":          "new_lead",
            "booking_link_requested":  False,
            "qualification":           {},
            "end_reason":              None,
        }
        logger.info("Call state initialized on call-started")
    else:
        logger.info("Call state already exists from assistant-request")

    return {"status": "ok"}


async def _handle_function_call(
    message: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    """
    Execute a tool call requested by the LLM during the conversation.
    Returns the tool result in the format Vapi expects.
    """
    func_call = message.get("functionCall", {})
    tool_name = func_call.get("name", "")
    arguments = func_call.get("parameters", "{}")
    if isinstance(arguments, dict):
        arguments = json.dumps(arguments)

    # Get the mutable call state — pass it to the dispatcher so handlers
    # can read and write contact_id, opportunity_id, etc.
    state = _call_state.get(call_id, {})

    logger.info("Executing tool call", extra={"tool": tool_name})

    result = await dispatcher.dispatch(
        tool_name=tool_name,
        arguments_json=arguments,
        contact_id=state.get("contact_id"),
        phone=state.get("phone"),
        call_state=state,
    )

    # Sync any contact_id updates back to the main state
    if state.get("contact_id") and call_id in _call_state:
        _call_state[call_id]["contact_id"] = state["contact_id"]

    # Handle Vapi flow control actions
    action = result.get("action", {})
    action_type = action.get("type", "") if isinstance(action, dict) else ""

    if action_type == "end-call":
        return {
            "result": result.get("result", "Thank you for calling. Goodbye!"),
            "action": {"type": "end-call"},
        }

    # Standard tool result — returned as text to the LLM
    return {"result": result.get("result", str(result))}


async def _handle_end_of_call(
    message: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    """
    Process the end-of-call report: generate a structured summary and
    push it to GHL as a note. Clean up call state.
    """
    logger.info("Processing end-of-call report")

    state = _call_state.pop(call_id, {})
    contact    = state.get("contact") or {}
    contact_id = state.get("contact_id") or contact.get("id")

    # Build transcript from Vapi's artifact
    artifact        = message.get("artifact", {})
    raw_transcript  = artifact.get("transcript", "")
    vapi_messages   = artifact.get("messages", [])

    if vapi_messages:
        transcript = [
            {
                "role":    m.get("role", "user"),
                "content": m.get("message") or m.get("content") or "",
            }
            for m in vapi_messages
            if m.get("message") or m.get("content")
        ]
    elif raw_transcript:
        transcript = [{"role": "user", "content": raw_transcript}]
    else:
        transcript = state.get("messages", [])

    summary = await summary_service.generate_and_save_summary(
        transcript=transcript,
        contact_id=contact_id,
        call_id=call_id,
    )

    logger.info(
        "Call ended and summarized",
        extra={
            "outcome":    summary.get("outcome"),
            "sentiment":  summary.get("sentiment"),
            "contact_id": contact_id,
        },
    )

    return {"status": "ok", "summary": summary}


def _handle_transcript(message: dict[str, Any], call_id: str) -> dict[str, Any]:
    """Accumulate real-time transcript chunks into call state."""
    role = message.get("role", "unknown")
    text = message.get("transcript", "")
    if call_id in _call_state and text:
        _call_state[call_id]["messages"].append({"role": role, "content": text})
    return {"status": "ok"}


def _handle_hang(call_id: str) -> dict[str, Any]:
    """Clean up state if Vapi sends a hang event without end-of-call-report."""
    _call_state.pop(call_id, None)
    logger.info("Call hung up — state cleared")
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_phone(call: dict[str, Any]) -> Optional[str]:
    """Extract the caller's phone number from the Vapi call object."""
    customer = call.get("customer", {})
    return customer.get("number") or call.get("phoneNumber", {}).get("number")


def _build_greeting(contact: Optional[dict[str, Any]]) -> str:
    """Build a personalized opening greeting."""
    if not contact:
        return (
            "Thank you for calling TaskDeskr. This is Aria, your AI front desk assistant. "
            "How can I help you today?"
        )
    first_name = contact.get("firstName", "")
    if first_name:
        return (
            f"Hi {first_name}! Thank you for calling TaskDeskr. "
            "This is Aria. How can I help you today?"
        )
    return (
        "Thank you for calling TaskDeskr. This is Aria, your AI front desk assistant. "
        "How can I help you today?"
    )
