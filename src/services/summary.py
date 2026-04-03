"""
TaskDeskr Voice Core — Call Summary Service
=============================================
Generates a structured summary at the end of each call using the LLM,
then pushes it back to GoHighLevel as a contact note.

The summary includes:
  - Call outcome (booked, escalated, no action, callback needed, etc.)
  - Key topics discussed
  - Actions taken during the call
  - Follow-up tasks
  - Sentiment assessment
  - Raw transcript excerpt
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
            "required": ["outcome", "topics", "actions_taken", "follow_up", "sentiment"],
            "properties": {
                "outcome": {
                    "type": "string",
                    "enum": [
                        "appointment_booked",
                        "escalated_to_human",
                        "information_provided",
                        "callback_scheduled",
                        "no_action",
                        "voicemail",
                        "other",
                    ],
                    "description": "Primary outcome of the call.",
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key topics or questions raised during the call.",
                },
                "actions_taken": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of actions executed (e.g. 'Booked appointment for 2026-04-01 at 2pm').",
                },
                "follow_up": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Pending tasks or follow-up items for the team.",
                },
                "sentiment": {
                    "type": "string",
                    "enum": ["positive", "neutral", "negative", "frustrated"],
                    "description": "Overall caller sentiment.",
                },
                "summary_text": {
                    "type": "string",
                    "description": "One-paragraph human-readable summary of the call.",
                },
            },
        },
    },
}

_SUMMARY_SYSTEM = """You are a call analyst. Given a voice call transcript, extract a structured summary.
Be factual and concise. Do not infer information not present in the transcript."""


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

    # Use Anthropic for summarization (Claude is the configured LLM provider)
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
        "outcome": "other",
        "topics": [],
        "actions_taken": [],
        "follow_up": [],
        "sentiment": "neutral",
        "summary_text": llm_result.get("content", "Summary unavailable."),
        "provider": llm_result.get("provider"),
    }


def _empty_summary(call_id: str) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "outcome": "no_action",
        "topics": [],
        "actions_taken": [],
        "follow_up": [],
        "sentiment": "neutral",
        "summary_text": "No transcript available.",
    }


def _format_note(summary: dict[str, Any], call_id: str) -> str:
    """Format the summary dict into a human-readable GHL note."""
    lines = [
        f"📞 CALL SUMMARY — {call_id}",
        f"Outcome: {summary.get('outcome', 'unknown').replace('_', ' ').title()}",
        f"Sentiment: {summary.get('sentiment', 'neutral').title()}",
    ]

    if topics := summary.get("topics"):
        lines.append(f"Topics: {', '.join(topics)}")

    if actions := summary.get("actions_taken"):
        lines.append("Actions Taken:")
        for a in actions:
            lines.append(f"  • {a}")

    if follow_up := summary.get("follow_up"):
        lines.append("Follow-Up:")
        for f in follow_up:
            lines.append(f"  • {f}")

    if text := summary.get("summary_text"):
        lines += ["", text]

    return "\n".join(lines)
