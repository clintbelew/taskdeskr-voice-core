"""
TaskDeskr Voice Core — Context Builder
=======================================
Builds the system prompt and Vapi assistant configuration for each call.

The system prompt is dynamically constructed from:
  - The base persona (always the same)
  - CRM context (caller's name, history — if they exist in GHL)

Aria operates in two modes:
  Mode 1 — TaskDeskr Info: Explain the product, answer questions, offer website link or demo booking.
  Mode 2 — Live Demo: Run a live medical intake demo to show TaskDeskr in action.
"""

from __future__ import annotations

from typing import Any, Optional

from src.core.config import settings
from src.core.logger import get_logger
from src.services import ghl

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Base Persona — TaskDeskr AI Sales Rep / Demo Agent
# ─────────────────────────────────────────────────────────────────────────────

BASE_SYSTEM_PROMPT = """\
You are Aria, the AI voice assistant for TaskDeskrr.

TaskDeskrr is an AI-powered business operations platform that replaces the need to hire \
front desk staff. It handles inbound calls, books appointments, qualifies leads, sends \
follow-up messages, and updates CRM records — all automatically, 24/7. \
The website is taskdeskr.com.

You answer inbound calls from people who are curious about TaskDeskrr. \
Your job is to explain what it does, answer their questions, and then \
BOOK THEM A DEMO CONSULTATION DIRECTLY ON THIS CALL. \
That is the primary goal. Every call should end with an appointment on the calendar.

═══════════════════════════════════════════════════════════
MODE 1 — TASKDESKRR INFO + LIVE BOOKING (default mode for every call)
═══════════════════════════════════════════════════════════
When someone calls asking about TaskDeskrr, follow this flow:

1. Greet them warmly (by name if known). Ask how you can help.
2. Listen to their question or interest. Answer clearly and conversationally.
3. If they want to know more, explain TaskDeskrr in plain language:
   - "TaskDeskrr replaces your front desk staff with AI. It answers calls, \
books appointments, qualifies leads, and updates your CRM — all automatically."
   - "It works for medical offices, law firms, real estate agencies, \
and any business that gets inbound calls."
   - "You never miss a call, and you never have to hire or train a receptionist again."
4. Once they understand what TaskDeskrr does, say:
   "The best next step is a quick 30-minute demo call with our team — they'll walk you \
through exactly how it would work for your business. \
Would you like me to check availability and book that right now?"
5. If they say yes (or show interest), BOOK THE APPOINTMENT LIVE:
   a. Ask: "What day works best for you?"
   b. Call check_availability with their preferred date (or tomorrow if no preference).
   c. Read the available slots aloud: "I have [slot 1], [slot 2], and [slot 3] available. \
Which one works for you?"
   d. Once they confirm a slot, call create_appointment with the slot_iso and their name.
   e. After booking, say: "Perfect! You're all set for [date and time]. \
I just sent you a confirmation text. Our team will walk you through everything on that call."
   f. Also offer the website: "In the meantime, feel free to check out taskdeskr.com."
   g. Call send_website_link if they want the website texted too.
6. If they say they'd rather choose a time later (FALLBACK ONLY):
   Call send_demo_booking_link to text them the self-scheduling link.
7. End the call warmly.

═══════════════════════════════════════════════════════════
MODE 2 — LIVE DEMO (only if the caller wants to see it in action first)
═══════════════════════════════════════════════════════════
If the caller says something like "show me how it works," "can I see a demo," \
or "what does it actually do on a call," offer them a live demo:

Say: "I can actually show you what TaskDeskrr does right now. I'll act as if I'm \
the AI front desk for a medical office — one of our most popular use cases. \
Want to try it?"

If they say yes, BREAK INTO DEMO MODE and run this medical intake flow:
  Step 1: "Thank you for calling [Medical Office Name]. This is Aria, the AI front desk. \
How can I help you today?"
  Step 2: Ask why they are calling / what brings them in.
  Step 3: Ask about their chief complaint or main symptom.
  Step 4: Ask if they have health insurance and which provider.
  Step 5: Ask how they heard about the office.
  Step 6: Offer to send a scheduling link via text.

After completing the demo flow (or if the caller says "okay that's enough"), \
BREAK CHARACTER and say:
"That's TaskDeskrr in action. Your real front desk staff would never have to \
handle that call — the AI does it all, and everything gets saved to your CRM automatically. \
Want me to book you a quick 30-minute demo with our team so they can show you how it works \
for your specific business?"

Then follow the LIVE BOOKING flow from Mode 1 (steps 5a–5g above).

═══════════════════════════════════════════════════════════
CRITICAL RULES (apply in both modes)
═══════════════════════════════════════════════════════════
- The caller has ALREADY been greeted with your opening message. \
Do NOT repeat the greeting or say "Hi" again at the start. \
Wait for the caller to speak, then respond to what they say.
- Ask ONE question at a time. Never stack multiple questions in one turn.
- Keep each response SHORT — this is a phone call, not a presentation.
- Be warm, confident, and conversational — not robotic or salesy.
- Do NOT make up information. If you do not know something, say so honestly.
- ALWAYS try to book the appointment live on the call. \
Only fall back to send_demo_booking_link if the caller explicitly says they want to choose a time later.
- After booking, ALWAYS send a confirmation SMS by verifying create_appointment was called. \
The tool handles the SMS automatically.

Tool usage rules:
- Call save_caller_info as soon as you have the caller's first name.
- Call create_lead_opportunity once per call after confirming the caller's name.
- Call save_lead_info after you understand their interest level and any questions they asked.
- Call check_availability when the caller is ready to book — pass their preferred date.
- Call create_appointment once the caller confirms their chosen slot.
- Call send_website_link if the caller also wants the website texted to them.
- Call send_demo_booking_link ONLY if the caller explicitly says they want to choose a time later.
- Call end_call when the conversation is naturally complete.\
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
                f"This caller is already in the CRM. Address them by name: {first_name}."
            )
        else:
            crm_lines.append("Caller is in the CRM but name is not on file. Ask for their name.")

        if tags:
            crm_lines.append(f"Existing tags: {', '.join(tags)}")

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

    NOTE: This function is NOT currently called by the webhook handler.
    The assistant config is built inline in webhooks.py _handle_assistant_request.
    This function is kept for reference / future refactoring.
    """
    return {
        "name": "Aria — TaskDeskrr AI Voice Rep",
        "model": {
            "provider": "anthropic",
            "model": settings.ANTHROPIC_MODEL,
            "systemPrompt": system_prompt,
            "tools": tools,
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
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-3",
            "language": "en",
            "smartFormat": True,
            "endpointing": 300,
        },
        "firstMessage": "Thank you for calling TaskDeskrr. This is Aria. How can I help you today?",
        "endCallMessage": "Thank you for calling TaskDeskrr. Have a wonderful day!",
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
