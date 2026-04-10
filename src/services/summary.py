"""
TaskDeskr Voice Core — Call Summary Service
=============================================
Generates a structured summary at the end of each call using the LLM,
then pushes it back to GoHighLevel as a contact note.

Summary fields (9 total):
  1. caller_type       — new lead / existing customer / support / urgent / other
  2. reason_for_call   — what the caller needed
  3. urgency_level     — low / medium / high
  4. action_taken      — what was done during the call
  5. follow_up_required — yes / no
  6. route_to          — who should handle next
  7. appointment_details — if any booking was made
  8. promised_next_step — what the caller was told would happen
  9. overall_summary   — one-paragraph human-readable summary
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.core.logger import get_logger
from src.core import router
from src.services import ghl

logger = get_logger(__name__)

# ── Summary schema ────────────────────────────────────────────────────────────
_SUMMARY_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_call_summary",
        "description": "Submit a structured summary of the completed call.",
        "parameters": {
            "type": "object",
            "required": [
                "caller_type",
                "reason_for_call",
                "urgency_level",
                "action_taken",
                "follow_up_required",
                "route_to",
                "promised_next_step",
                "overall_summary",
            ],
            "properties": {
                "caller_type": {
                    "type": "string",
                    "enum": [
                        "new_lead",
                        "existing_customer",
                        "support",
                        "urgent",
                        "other",
                    ],
                    "description": "Type of caller based on their intent and history.",
                },
                "reason_for_call": {
                    "type": "string",
                    "description": "Brief description of why the caller called (1-2 sentences).",
                },
                "urgency_level": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Urgency level of the caller's need.",
                },
                "action_taken": {
                    "type": "string",
                    "description": "What was done during the call (e.g. 'Booked demo for April 12 at 2pm', 'Sent booking link via SMS', 'Collected lead info').",
                },
                "follow_up_required": {
                    "type": "string",
                    "enum": ["yes", "no"],
                    "description": "Whether the team needs to follow up after this call.",
                },
                "route_to": {
                    "type": "string",
                    "description": "Who should handle the next step (e.g. 'Sales team', 'Demo team', 'Support', 'No routing needed').",
                },
                "appointment_details": {
                    "type": "string",
                    "description": "Appointment date, time, and type if a booking was made. Leave blank if no appointment was booked.",
                },
                "promised_next_step": {
                    "type": "string",
                    "description": "Exactly what the caller was told would happen next (e.g. 'Confirmation text sent', 'Team will call back within 24 hours', 'Booking link sent via SMS').",
                },
                "overall_summary": {
                    "type": "string",
                    "description": "One-paragraph human-readable summary of the full call — what happened, what was resolved, and what is pending.",
                },
            },
        },
    },
}

_SUMMARY_SYSTEM = """You are a call analyst for TaskDeskr, an AI operations platform. \
Given a voice call transcript, you MUST call the submit_call_summary tool with a structured summary.

Extract exactly these fields:
- caller_type: new_lead / existing_customer / support / urgent / other
- reason_for_call: why they called (1-2 sentences)
- urgency_level: low / medium / high
- action_taken: what was done on the call (booking, link sent, info provided, etc.)
- follow_up_required: yes / no
- route_to: who handles next (Sales team, Demo team, Support, No routing needed, etc.)
- appointment_details: date/time/type if booked, blank if not
- promised_next_step: exactly what the caller was told would happen next
- overall_summary: one paragraph describing the full call

Be factual and concise. Only use information present in the transcript. You MUST call the tool."""


async def generate_and_save_summary(
    transcript: list[dict[str, str]],
    contact_id: Optional[str],
    call_id: str,
    provider_override: Optional[str] = None,
) -> dict[str, Any]:
    """
    Generate a structured call summary from the transcript and save it to GHL.

    Parameters
    ----------
    transcript      : List of {"role": "user"|"assistant", "content": "..."} messages
    contact_id      : GHL contact ID to attach the note to (may be None for new callers)
    call_id         : Vapi call ID for reference
    provider_override: Force a specific LLM provider for summarization

    Returns
    -------
    Structured summary dict
    """
    if not transcript:
        logger.warning("Empty transcript — skipping summary generation")
        return _empty_summary(call_id)

    logger.info("Generating call summary", extra={"call_id": call_id})

    result = await router.complete(
        messages=transcript,
        system_prompt=_SUMMARY_SYSTEM,
        tools=[_SUMMARY_TOOL],
        task_type="summarize",
        provider_override=provider_override or "anthropic",
        temperature=0.1,
        max_tokens=1024,
    )

    summary = _parse_summary(result, call_id)

    # Push to GHL as a contact note
    if contact_id:
        note_body = _format_note(summary, call_id)
        try:
            await ghl.add_note(contact_id=contact_id, body=note_body)
            logger.info("Summary note saved to GHL", extra={"contact_id": contact_id})
        except ghl.GHLError as exc:
            logger.error(
                "Failed to save summary note to GHL",
                extra={"contact_id": contact_id, "error": str(exc)},
            )

    return summary


def _parse_summary(llm_result: dict[str, Any], call_id: str) -> dict[str, Any]:
    """Extract the structured summary from the LLM tool call response."""
    tool_calls = llm_result.get("tool_calls") or []
    for tc in tool_calls:
        if tc.get("name") == "submit_call_summary":
            try:
                data = json.loads(tc["arguments"])
                data["call_id"] = call_id
                data["provider"] = llm_result.get("provider")
                return data
            except (json.JSONDecodeError, KeyError) as exc:
                logger.error("Failed to parse summary tool call", extra={"error": str(exc)})

    # Fallback: use raw content if tool call was not triggered
    return {
        "call_id": call_id,
        "caller_type": "other",
        "reason_for_call": "Unknown",
        "urgency_level": "low",
        "action_taken": "None",
        "follow_up_required": "no",
        "route_to": "No routing needed",
        "appointment_details": "",
        "promised_next_step": "None",
        "overall_summary": llm_result.get("content", "Summary unavailable."),
        "provider": llm_result.get("provider"),
    }


def _empty_summary(call_id: str) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "caller_type": "other",
        "reason_for_call": "No transcript available.",
        "urgency_level": "low",
        "action_taken": "None",
        "follow_up_required": "no",
        "route_to": "No routing needed",
        "appointment_details": "",
        "promised_next_step": "None",
        "overall_summary": "No transcript available.",
    }


def _format_note(summary: dict[str, Any], call_id: str) -> str:
    """Format the summary dict into a human-readable GHL note."""
    lines = [
        f"📞 TASKDESKR CALL SUMMARY",
        f"Call ID: {call_id}",
        "",
        f"Caller Type:       {summary.get('caller_type', 'other').replace('_', ' ').title()}",
        f"Reason for Call:   {summary.get('reason_for_call', 'Unknown')}",
        f"Urgency Level:     {summary.get('urgency_level', 'low').title()}",
        f"Action Taken:      {summary.get('action_taken', 'None')}",
        f"Follow-Up Required:{summary.get('follow_up_required', 'no').title()}",
        f"Route To:          {summary.get('route_to', 'No routing needed')}",
    ]

    if appt := summary.get("appointment_details"):
        lines.append(f"Appointment:       {appt}")

    lines.append(f"Promised Next Step:{summary.get('promised_next_step', 'None')}")

    if text := summary.get("overall_summary"):
        lines += ["", "─" * 40, text]

    return "\n".join(lines)
