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

State is persisted in Redis (with in-memory fallback) via call_state manager.
Reference: https://docs.vapi.ai/server-url
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

from src.core.config import settings
from src.core.logger import get_logger, set_call_context, clear_call_context
from src.core.state import call_state
from src.services import context as ctx_service
from src.services import summary as summary_service
from src.tools import dispatcher
from src.tools.definitions import TOOL_DEFINITIONS

logger = get_logger(__name__)


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
    phone      = _extract_phone(call)

    set_call_context(call_id=call_id, phone=phone)
    logger.info("Vapi event received", extra={"event_type": event_type})

    try:
        if event_type == "assistant-request":
            return await _handle_assistant_request(message, call_id, phone)
        elif event_type == "call-started":
            return await _handle_call_started(message, call_id, phone)
        elif event_type in ("function-call", "tool-calls"):
            return await _handle_function_call(message, call_id)
        elif event_type == "end-of-call-report":
            return await _handle_end_of_call(message, call_id)
        elif event_type == "transcript":
            return await _handle_transcript(message, call_id)
        elif event_type == "hang":
            return await _handle_hang(call_id)
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
    Vapi calls this BEFORE the call begins and waits for a response.
    CRITICAL: Must return in < 20 seconds or Vapi rejects the call.

    Strategy: Return the assistant config IMMEDIATELY using the base prompt
    (no GHL lookup here). The GHL lookup and CRM personalisation happen in
    call-started, which fires after the call connects with no timeout risk.
    """
    logger.info("Handling assistant-request — returning config instantly (no GHL lookup)")

    # Use the base system prompt without CRM personalisation.
    # CRM context will be resolved in call-started once the call is live.
    system_prompt = ctx_service.BASE_SYSTEM_PROMPT

    # Store minimal placeholder state so call-started knows to do the full init.
    await call_state.set(call_id, {
        "system_prompt":          system_prompt,
        "contact":                None,
        "contact_id":             None,
        "phone":                  phone,
        "transcript":             [],
        "messages":               [],
        "caller_first_name":      "",
        "caller_last_name":       "",
        "caller_email":           "",
        "opportunity_id":         None,
        "opportunity_name":       None,
        "pipeline_stage":         "new_lead",
        "booking_link_requested": False,
        "qualification":          {},
        "end_reason":             None,
        "crm_init_done":          False,  # call-started will flip this to True
    })

    logger.info(
        "Call state placeholder set — CRM init deferred to call-started",
        extra={"call_id": call_id, "phone": phone},
    )

    # Return the full assistant config immediately
    return {
        "assistant": {
            "name": "TaskDesker AI Operations",
            "model": {
                "provider": "anthropic",
                "model": "claude-sonnet-4-5-20250929",
                "systemPrompt": system_prompt,
                "tools": TOOL_DEFINITIONS,
                "temperature": 0.4,
            },
            "voice": {
                "provider": "11labs",
                "voiceId": "21m00Tcm4TlvDq8ikWAM",  # Rachel — confirmed working
                "stability": 0.5,
                "similarityBoost": 0.75,
                "useSpeakerBoost": True,
                # No pronunciation dictionary — ElevenLabs reads 'TaskDeskr' correctly natively
            },
            "firstMessage": "Hey, this is TaskDesker. I help manage calls, scheduling, and follow-ups for the team. What can I help you get taken care of today?",
            "endCallMessage": "I've got everything noted. You're all set — talk soon.",
            "endCallPhrases": [
                "goodbye", "bye bye", "talk later", "have a good day", "thank you bye"
            ],
            "recordingEnabled": True,
            "maxDurationSeconds": 600,
            "silenceTimeoutSeconds": 30,
            "responseDelaySeconds": 0.4,
            "numWordsToInterruptAssistant": 3,
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-3",
                "language": "en",
                "endpointing": 300,
            },
            "backgroundDenoisingEnabled": True,
        }
    }


async def _handle_call_started(
    message: dict[str, Any],
    call_id: str,
    phone: Optional[str],
) -> dict[str, Any]:
    """
    Runs after the call connects. Performs the GHL lookup and fully initialises
    call state — safe here because there is no timeout risk.

    Two scenarios:
    A) assistant-request already ran → state exists with crm_init_done=False
       → do the GHL lookup now and update state with CRM data
    B) no assistant-request (pre-built assistant mode) → state does not exist
       → do full init from scratch
    """
    state_exists = await call_state.exists(call_id)
    crm_done     = False
    if state_exists:
        existing = await call_state.get(call_id)
        crm_done = existing.get("crm_init_done", False)

    if not crm_done:
        logger.info("call-started: running GHL lookup and completing CRM init",
                    extra={"call_id": call_id, "phone": phone})
        try:
            system_prompt, contact = await ctx_service.build_context(phone=phone or "")
            contact_id = contact.get("id") if contact else None
        except Exception as exc:
            logger.error("GHL lookup failed in call-started — using base prompt",
                         extra={"error": str(exc)})
            system_prompt = ctx_service.BASE_SYSTEM_PROMPT
            contact       = None
            contact_id    = None

        crm_data = {
            "system_prompt":     system_prompt,
            "contact":           contact,
            "contact_id":        contact_id,
            "caller_first_name": contact.get("firstName", "") if contact else "",
            "caller_last_name":  contact.get("lastName", "")  if contact else "",
            "caller_email":      contact.get("email", "")     if contact else "",
            "crm_init_done":     True,
        }

        if state_exists:
            await call_state.update(call_id, crm_data)
        else:
            # No prior assistant-request — build full state from scratch
            await call_state.set(call_id, {
                **crm_data,
                "phone":                  phone,
                "transcript":             [],
                "messages":               [],
                "opportunity_id":         None,
                "opportunity_name":       None,
                "pipeline_stage":         "new_lead",
                "booking_link_requested": False,
                "qualification":          {},
                "end_reason":             None,
            })

        logger.info(
            "CRM init complete in call-started",
            extra={"call_id": call_id, "contact_id": contact_id},
        )
    else:
        logger.info("call-started: CRM already initialised — skipping",
                    extra={"call_id": call_id})

    return {"status": "ok"}


async def _handle_function_call(
    message: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    """
    Execute tool call(s) requested by the LLM and return all results.
    Handles both legacy "function-call" and current "tool-calls" event types.
    Supports parallel tool calls — Claude sometimes fires multiple tools simultaneously.
    Returns results in Vapi's expected format: {"results": [{"toolCallId": X, "result": Y}, ...]}
    """
    import asyncio

    # Load state from Redis once (shared across all parallel tool calls)
    state = await call_state.get(call_id)

    # Edge case: state is empty (pre-built assistant, no assistant-request fired)
    if not state:
        call_obj        = message.get("call", {})
        phone_from_call = _extract_phone(call_obj)
        state = {"phone": phone_from_call, "contact_id": None, "messages": [], "qualification": {}}
        if phone_from_call:
            logger.info(
                "Empty state on function-call — resolving contact from phone",
                extra={"phone": phone_from_call},
            )
            try:
                from src.services import ghl as ghl_svc
                contact = await ghl_svc.lookup_contact_by_phone(phone_from_call)
                if not contact:
                    contact = await ghl_svc.create_contact(phone=phone_from_call)
                if contact:
                    state["contact_id"] = contact.get("id")
                    state["contact"]    = contact
            except Exception as exc:
                logger.error("GHL lookup failed in function-call fallback", extra={"error": str(exc)})
        await call_state.set(call_id, state)
    elif not state.get("phone"):
        # State exists but phone is missing — extract from message
        call_obj        = message.get("call", {})
        phone_from_call = _extract_phone(call_obj)
        if phone_from_call:
            state = await call_state.update(call_id, {"phone": phone_from_call})

    # Build list of (tool_call_id, tool_name, arguments) tuples to execute
    tool_call_list = message.get("toolCallList", [])
    if tool_call_list:
        # Current Vapi format: toolCallList array (may contain multiple parallel calls)
        calls_to_run = []
        for tc in tool_call_list:
            tc_id    = tc.get("id", "")
            func_obj = tc.get("function", {})
            tc_name  = func_obj.get("name", tc.get("name", ""))
            tc_args  = func_obj.get("arguments", tc.get("arguments", "{}"))
            if isinstance(tc_args, dict):
                tc_args = json.dumps(tc_args)
            calls_to_run.append((tc_id, tc_name, tc_args))
    else:
        # Legacy function-call format (single call)
        func_call = message.get("functionCall", {})
        tc_id     = func_call.get("id", "")
        tc_name   = func_call.get("name", "")
        tc_args   = func_call.get("parameters", "{}")
        if isinstance(tc_args, dict):
            tc_args = json.dumps(tc_args)
        calls_to_run = [(tc_id, tc_name, tc_args)]

    logger.info(
        "Executing tool call(s)",
        extra={"tools": [c[1] for c in calls_to_run], "count": len(calls_to_run)},
    )

    # Execute all tool calls (sequentially to avoid race conditions on shared state)
    results = []
    end_call_action = None
    for tc_id, tc_name, tc_args in calls_to_run:
        result = await dispatcher.dispatch(
            tool_name=tc_name,
            arguments_json=tc_args,
            contact_id=state.get("contact_id"),
            phone=state.get("phone"),
            call_state=state,
        )
        result_text = result.get("result", str(result))
        results.append({"toolCallId": tc_id, "result": result_text})
        # Check for end-call action
        action = result.get("action", {})
        if isinstance(action, dict) and action.get("type") == "end-call":
            end_call_action = {"type": "end-call"}

    # Persist any state mutations back to Redis
    await call_state.set(call_id, state)

    # Return all results; include end-call action if any tool triggered it
    response = {"results": results}
    if end_call_action:
        response["action"] = end_call_action
    return response


async def _handle_end_of_call(
    message: dict[str, Any],
    call_id: str,
) -> dict[str, Any]:
    """
    Process the end-of-call report: generate a structured summary and
    push it to GHL as a note. Clean up call state from Redis.
    """
    logger.info("Processing end-of-call report")

    # Pop state from Redis (removes it after reading)
    state      = await call_state.delete(call_id)
    contact    = state.get("contact") or {}
    contact_id = state.get("contact_id") or contact.get("id")

    # Fallback: resolve contact from phone if not in state
    if not contact_id:
        call_obj = message.get("call", {})
        phone    = _extract_phone(call_obj) or state.get("phone")
        if phone:
            logger.info("No contact in state — looking up GHL contact at end-of-call", extra={"phone": phone})
            try:
                from src.services import ghl as ghl_svc
                contact = await ghl_svc.lookup_contact_by_phone(phone)
                if not contact:
                    contact = await ghl_svc.create_contact(phone=phone)
                if contact:
                    contact_id = contact.get("id")
                    logger.info("GHL contact resolved at end-of-call", extra={"contact_id": contact_id})
            except Exception as exc:
                logger.error("Failed to resolve GHL contact at end-of-call", extra={"error": str(exc)})

    # Build transcript from Vapi's artifact
    artifact       = message.get("artifact", {})
    raw_transcript = artifact.get("transcript", "")
    vapi_messages  = artifact.get("messages", [])

    if vapi_messages:
        # Vapi messages can have roles: "user", "bot", "tool_call", "tool_result", "system"
        # Anthropic only accepts "user" and "assistant" roles in the messages array.
        # Map "bot" -> "assistant"; skip "tool_call", "tool_result", "system" roles.
        _ROLE_MAP = {"user": "user", "bot": "assistant", "assistant": "assistant"}
        transcript = [
            {
                "role":    _ROLE_MAP[m.get("role", "user")],
                "content": m.get("message") or m.get("content") or "",
            }
            for m in vapi_messages
            if (m.get("message") or m.get("content"))
            and m.get("role") in _ROLE_MAP
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
        "Call ended and summarised",
        extra={
            "outcome":    summary.get("outcome"),
            "sentiment":  summary.get("sentiment"),
            "contact_id": contact_id,
        },
    )
    return {"status": "ok", "summary": summary}


async def _handle_transcript(message: dict[str, Any], call_id: str) -> dict[str, Any]:
    """Accumulate real-time transcript chunks into call state."""
    role = message.get("role", "unknown")
    text = message.get("transcript", "")
    if text and await call_state.exists(call_id):
        state    = await call_state.get(call_id)
        messages = state.get("messages", [])
        messages.append({"role": role, "content": text})
        await call_state.update(call_id, {"messages": messages})
    return {"status": "ok"}


async def _handle_hang(call_id: str) -> dict[str, Any]:
    """Clean up state if Vapi sends a hang event without end-of-call-report."""
    await call_state.delete(call_id)
    logger.info("Call hung up — state cleared from Redis")
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_phone(call: dict[str, Any]) -> Optional[str]:
    """Extract the caller's phone number from the Vapi call object."""
    customer = call.get("customer", {})
    return customer.get("number") or call.get("phoneNumber", {}).get("number")


def _build_greeting(contact: Optional[dict[str, Any]]) -> str:
    """Build a personalised opening greeting based on CRM data."""
    if not contact:
        return (
            "Hey, this is TaskDesker. I help manage calls, scheduling, and follow-ups for the team. "
            "What can I help you get taken care of today?"
        )
    first_name = contact.get("firstName", "")
    if first_name:
        return (
            f"Hey {first_name}, this is TaskDesker. I help manage calls, scheduling, and follow-ups for the team. "
            "What can I help you get taken care of today?"
        )
    return (
        "Hey, this is TaskDesker. I help manage calls, scheduling, and follow-ups for the team. "
        "What can I help you get taken care of today?"
    )
