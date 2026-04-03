"""
TaskDeskr Voice Core — Context Builder
=======================================
Builds the system prompt and Vapi assistant configuration for each call.

The system prompt is dynamically constructed from:
  - The base persona (always the same)
  - CRM context (caller's name, history, tags — if they exist in GHL)

This is what makes the AI feel like it knows the caller and can skip
redundant questions for returning patients.
"""

from __future__ import annotations

from typing import Any, Optional

from src.core.logger import get_logger
from src.services import ghl

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Base Persona — TaskDeskr AI Front Desk
# ─────────────────────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """\
You are Aria, the AI front desk assistant for TaskDeskr. \
You answer inbound calls professionally, warmly, and efficiently.

Your primary goals on every call:
1. Greet the caller and confirm their name.
2. Understand why they are calling.
3. Collect key qualification information (insurance, chief complaint, referral source).
4. If they want to schedule an appointment, let them know the team will send a booking link.
5. End the call warmly.

Qualification questions to ask (naturally, not as a form):
- Do you currently have health insurance?
- Which insurance provider are you with?
- What is the main reason you are calling today, or what symptoms are you experiencing?
- How did you hear about us?

Rules:
- Be conversational and warm — not robotic.
- Ask one question at a time. Do not overwhelm the caller.
- As soon as you have the caller's first name, call the save_caller_info tool.
- After collecting qualification info, call save_qualification_data.
- Call create_lead_opportunity once per call after confirming the caller's name.
- If the caller wants to book an appointment, call send_booking_link and tell them \
the team will text them a scheduling link shortly.
- Do NOT attempt to book a live appointment on this call.
- Do NOT make up information. If you do not know something, say so honestly.
- Keep responses concise — this is a phone call, not a chat.
- End the call with end_call when the conversation is complete.\
"""


# ─────────────────────────────────────────────────────────────────────────────
# Context Builder
# ─────────────────────────────────────────────────────────────────────────────

async def build_context(
    phone: str,
    agent_persona: str = BASE_SYSTEM_PROMPT,
    extra_instructions: str = "",
) -> tuple[str, Optional[dict[str, Any]]]:
    """
    Build a system prompt enriched with CRM context for the given caller.

    Returns
    -------
    (system_prompt: str, contact: dict | None)
        system_prompt — fully assembled string ready for LLM injection
        contact       — raw GHL contact dict (or None if not found)
    """
    contact = await ghl.lookup_contact_by_phone(phone)

    system_prompt = _assemble_prompt(agent_persona, contact, extra_instructions)

    logger.info(
        "Context built",
        extra={
            "phone": phone,
            "contact_found": contact is not None,
            "contact_id": contact.get("id") if contact else None,
        },
    )
    return system_prompt, contact


def _assemble_prompt(
    persona: str,
    contact: Optional[dict[str, Any]],
    extra_instructions: str,
) -> str:
    """Combine persona, CRM context, and extra instructions into a single prompt."""
    parts = [persona.strip()]

    if contact:
        first_name = contact.get("firstName") or contact.get("first_name") or ""
        last_name  = contact.get("lastName")  or contact.get("last_name")  or ""
        tags       = contact.get("tags", [])
        full_name  = f"{first_name} {last_name}".strip()

        crm_lines = ["\n--- CALLER CRM CONTEXT ---"]

        if full_name:
            crm_lines.append(f"Caller name: {full_name}")
            crm_lines.append(
                f"This caller is already in the CRM. Greet them by name: "
                f"'Hi {first_name}, thanks for calling TaskDeskr!'"
            )
        else:
            crm_lines.append("Caller is in the CRM but name is not on file. Ask for their name.")

        if tags:
            crm_lines.append(f"Existing tags: {', '.join(tags)}")

        # Check for prior visit count custom field
        visit_count = _get_custom_field(contact, "contact.appointment_visit_count")
        if visit_count and visit_count not in ("0", ""):
            crm_lines.append(f"Prior visit count: {visit_count}")
            crm_lines.append("This is a returning patient. Acknowledge their return warmly.")

        crm_lines.append("--- END CRM CONTEXT ---")
        parts.append("\n".join(crm_lines))

    else:
        parts.append(
            "\n\nThis is a new caller — not yet in the CRM. "
            "Ask for their name early in the conversation."
        )

    if extra_instructions:
        parts.append(f"\nADDITIONAL INSTRUCTIONS:\n{extra_instructions.strip()}")

    return "\n".join(parts)


def _get_custom_field(contact: dict[str, Any], key: str) -> Optional[str]:
    """Extract a custom field value from a GHL contact object."""
    custom_fields = contact.get("customField") or contact.get("customFields") or []
    for field in custom_fields:
        if field.get("key") == key or field.get("id") == key:
            return str(field.get("value") or field.get("fieldValue") or "")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Vapi Assistant Configuration
# ─────────────────────────────────────────────────────────────────────────────

def build_assistant_config(system_prompt: str, tools: list[dict]) -> dict[str, Any]:
    """
    Build the full Vapi assistant configuration object.
    Returned in response to the 'assistant-request' webhook event.
    """
    return {
        "name": "Aria — TaskDeskr AI Front Desk",
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt}
            ],
            "tools": tools,
            "temperature": 0.4,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": "rachel",
        },
        "firstMessage": (
            "Thank you for calling TaskDeskr. This is Aria, your AI front desk assistant. "
            "How can I help you today?"
        ),
        "endCallMessage": "Thank you for calling TaskDeskr. Have a wonderful day!",
        "endCallPhrases": [
            "goodbye", "bye bye", "talk later", "have a good day", "thank you bye"
        ],
        "recordingEnabled": True,
        "hipaaEnabled": False,
        "maxDurationSeconds": 600,
        "silenceTimeoutSeconds": 30,
        "responseDelaySeconds": 0.5,
        "llmRequestDelaySeconds": 0.1,
        "numWordsToInterruptAssistant": 3,
    }
