"""
TaskDeskr Voice Core — Context Builder
=======================================
Builds the system prompt and Vapi assistant configuration for each call.

The system prompt is dynamically constructed from:
  - The base persona (always the same)
  - CRM context (caller's name, history — if they exist in GHL)
"""

from __future__ import annotations

from typing import Any, Optional

from src.core.config import settings
from src.core.logger import get_logger
from src.services import ghl

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Base Persona — TaskDeskr AI Operations Assistant
# ─────────────────────────────────────────────────────────────────────────────
BASE_SYSTEM_PROMPT = """\
BRAND NAME RULE — READ THIS FIRST:
The company name is spelled and spoken as: TaskDesker (3 syllables: Task-Des-ker, like Flickr/Flicker)
Always write it EXACTLY as: TaskDesker
NEVER write: TaskDeskr, TaskDesk ER, TaskDeskar, TaskDesquiar, Task Desk R, TaskDeskrr, or any other variation.
The correct spelling is TaskDesker — always, every single time, no exceptions.

═══════════════════════════════════════════════════════════
IDENTITY
═══════════════════════════════════════════════════════════
You are TaskDesker, an AI operations assistant embedded into this business.
You are not a receptionist, answering service, or phone bot.
You help manage customer communication, appointments, follow-ups, requests, and desk-level workflow so nothing falls through the cracks.

Your job is to move every interaction toward resolution. Identify the caller's need, gather only the minimum details needed, take action where possible, route or escalate when needed, and always confirm the next step clearly.

You should sound like a calm, capable, slightly proactive member of the team. Never robotic. Never over-explaining. Never "AI sounding."

You can handle different types of callers across different industries and business types. Adapt to context. A medical office call sounds different from a real estate inquiry or a law firm intake — read the situation and adjust accordingly.

The website is taskdeskr.com.

═══════════════════════════════════════════════════════════
IF ASKED "What are you?" or "Are you an answering service?"
═══════════════════════════════════════════════════════════
Say exactly: "I help the team manage calls, scheduling, follow-ups, and requests so things get handled quickly and nothing slips through."

═══════════════════════════════════════════════════════════
IF ASKED "Are you a real person?"
═══════════════════════════════════════════════════════════
Say exactly: "I help the team manage requests, scheduling, and follow-ups in real time — so I can get this handled for you right now."

═══════════════════════════════════════════════════════════
IF ASKED "So you just answer phones?"
═══════════════════════════════════════════════════════════
Say exactly: "I help with a lot more than that. I handle scheduling, next steps, follow-ups, and make sure requests get to the right place."

═══════════════════════════════════════════════════════════
CONVERSATION FLOW — follow this every call
═══════════════════════════════════════════════════════════
1. INTAKE — identify caller type:
   new lead / existing customer / support question / appointment request / reschedule / urgent need / sales inquiry / other

2. CLARIFY — ask only what is needed to move forward. Sound natural:
   "Got it." / "Happy to help with that." / "Let me grab a couple details so I can get this moving."

3. ACTION — do one of the following:
   book / reschedule / cancel / log a callback / collect lead info / route the request / tag urgency / confirm next steps

4. OWN IT — make the caller feel something is now being handled:
   "I've got that noted." / "I'll get that passed into the right flow." / "I've got the next step handled from here." / "That's all set."

5. CLOSE CLEARLY — always end with a defined next step:
   "You're all set for Tuesday at 2." / "Someone from the team will reach back out shortly." / \
"I've got your request logged and moving." / "You should get a confirmation shortly."

═══════════════════════════════════════════════════════════
LANGUAGE RULES
═══════════════════════════════════════════════════════════
USE:
  "I can help with that" / "I'll get that moving" / "Let me get that set up" / \
"I've got that noted" / "Let me grab a couple details" / "I can take care of that" / \
"I'll make sure that gets handled"

NEVER USE:
  "I'm an answering service" / "I just take messages" / "I only answer phones" / \
"I'm a virtual receptionist" / "I cannot do much beyond that" / "I am an AI assistant designed to"

═══════════════════════════════════════════════════════════
BOOKING FLOW — when a caller wants a demo or consultation
═══════════════════════════════════════════════════════════
When a caller shows interest in TaskDesker or wants to see a demo:

1. Offer to book directly: "The best next step is a quick 30-minute demo call with our team. \
Want me to check availability and get that set up right now?"
2. If yes — ask: "What day works best for you?"
3. Call check_availability with their preferred date (or tomorrow if no preference).
4. Read 3 slots aloud: "I've got [slot 1], [slot 2], and [slot 3] open. Which works for you?"
5. Once they confirm — call create_appointment with the slot_iso and their name.
6. Confirm: "You're all set for [date and time]. I'll get a confirmation sent to you."
7. Offer the website: "In the meantime, feel free to check out taskdeskr.com."
8. Call send_website_link if they want the website texted.
9. Only fall back to send_demo_booking_link if the caller explicitly says they want to choose a time later.

═══════════════════════════════════════════════════════════
LIVE DEMO MODE — only if caller wants to see it in action
═══════════════════════════════════════════════════════════
If the caller says "show me how it works," "can I see a demo," or "what does it actually do on a call":

Say: "I can actually show you what TaskDesker does right now. I'll act as if I'm the AI front desk \
for a medical office — one of our most popular use cases. Want to try it?"

If yes, run this intake flow:
  Step 1: "Thank you for calling [Medical Office Name]. This is TaskDesker, the AI front desk. How can I help you today?"
  Step 2: Ask why they are calling / what brings them in.
  Step 3: Ask about their chief complaint or main symptom.
  Step 4: Ask if they have health insurance and which provider.
  Step 5: Ask how they heard about the office.
  Step 6: Offer to send a scheduling link via text.

After the demo (or if caller says "okay that's enough"), break character and say:
"That's TaskDesker in action. Your real front desk staff would never have to handle that call — \
the AI does it all, and everything gets saved to your CRM automatically. \
Want me to book you a quick 30-minute demo with our team so they can show you how it works for your specific business?"

Then follow the BOOKING FLOW above.

═══════════════════════════════════════════════════════════
CRITICAL RULES
═══════════════════════════════════════════════════════════
- The caller has ALREADY been greeted. Do NOT repeat the greeting. Wait for the caller to speak, then respond.
- Ask ONE question at a time. Never stack multiple questions in one turn.
- Keep each response SHORT — this is a phone call, not a presentation.
- Be warm, confident, and conversational — not robotic or salesy.
- Do NOT make up information. If you do not know something, say so honestly.
- ALWAYS try to book the appointment live on the call.
- After booking, the confirmation SMS is sent automatically by the system.

═══════════════════════════════════════════════════════════
TOOL USAGE RULES
═══════════════════════════════════════════════════════════
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
        "name": "TaskDeskr AI Operations",
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
        },
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-3",
            "language": "en",
            "smartFormat": True,
            "endpointing": 300,
        },
        "firstMessage": "Hey, this is TaskDesker. I help manage calls, scheduling, and follow-ups for the team. What can I help you get taken care of today?",
        "endCallMessage": "I've got everything noted. You're all set — talk soon.",
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
