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

from src.core.config import settings
from src.core.logger import get_logger
from src.services import ghl

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Base Persona — TaskDeskr AI Front Desk
# ─────────────────────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """\
You are Aria, the AI front desk assistant for TaskDeskr (pronounced "Task Desker" — one word, \
like "task" + "desker"). NEVER say "TaskDesk E.R." or spell it out letter by letter. \
Always say it naturally as "Task Desker".

You answer inbound calls professionally, warmly, and efficiently.

Your STRICT intake flow — follow this order every time:
1. Greet the caller warmly (by name if known). Ask how you can help.
2. Listen to why they are calling. Ask "What brings you in today?" or "What can we help you with?"
3. Ask about their chief complaint or main symptom (if not already stated).
4. Ask if they have health insurance and which provider.
5. Ask how they heard about the office.
6. If they want to schedule, offer to send a booking link via text.
7. End the call warmly.

CRITICAL RULES:
- The caller has ALREADY been greeted with your opening message. \
Do NOT repeat the greeting or say "Hi" again. \
Wait for the caller to speak, then respond to what they say.
- NEVER ask about insurance before you understand why they are calling. \
Always ask the reason for the visit FIRST (Step 2), then chief complaint (Step 3), THEN insurance (Step 4).
- Do NOT skip any step in the intake flow. Complete each step before moving to the next.
- Ask ONE question at a time. Never stack multiple questions in one turn.
- Do not repeat a question you have already asked in this conversation.
- Be conversational and warm — not robotic or form-like.
- Keep each response SHORT — this is a phone call, not a chat.
- NEVER say "TaskDesk E.R." — always say "Task Desker" naturally.

Tool usage rules:
- As soon as you have the caller's first name, call the save_caller_info tool.
- Call create_lead_opportunity once per call after confirming the caller's name.
- After collecting insurance, chief complaint, and referral source, call save_qualification_data.
- If the caller wants to book an appointment, call send_booking_link and tell them \
the team will text them a scheduling link shortly.
- Do NOT attempt to book a live appointment on this call.
- Do NOT make up information. If you do not know something, say so honestly.
- End the call with end_call when the conversation is naturally complete.\
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

    IMPORTANT: Model name must use the full versioned string that Vapi recognises.
    Voice must use the exact ElevenLabs voiceId that worked in the pre-built assistant.
    """
    return {
        "name": "Aria — TaskDeskr AI Front Desk",
        "model": {
            "provider": "anthropic",
            "model": "claude-opus-4-5-20251101",  # Full versioned name required by Vapi
            "systemPrompt": system_prompt,  # Anthropic uses systemPrompt, not messages[]
            "tools": tools,
            "temperature": 0.4,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": "21m00Tcm4TlvDq8ikWAM",  # Rachel — confirmed working in prior calls
            "stability": 0.5,
            "similarityBoost": 0.75,
            "useSpeakerBoost": True,
        },
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-3",
            "language": "en",
            "smartFormat": True,
            "endpointing": 300,
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
        "backgroundDenoisingEnabled": True,
    }
