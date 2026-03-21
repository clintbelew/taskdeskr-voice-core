"""
TaskDeskr Voice Core — Context Builder
========================================
Assembles a rich system prompt for the LLM by pulling prior CRM data
from GoHighLevel before the call begins.

The context builder is called once at call-start (assistant-request or
call-started event) and returns a system prompt string that is injected
into every subsequent LLM completion for that call.

Context includes:
  - Caller identity (name, email)
  - Prior tags (intent signals, lead status)
  - Recent notes (last 3)
  - Open opportunities
  - Agent persona and task instructions
"""

from __future__ import annotations

from typing import Any, Optional

from src.core.logger import get_logger
from src.services import ghl

logger = get_logger(__name__)

# ── Default agent persona ─────────────────────────────────────────────────────
_BASE_PERSONA = """You are a professional AI voice assistant for TaskDeskr.
Your role is to help callers with scheduling, information, and support.
Be concise, warm, and professional. Keep responses under 3 sentences unless more detail is needed.
Never fabricate information — if you don't know something, say so and offer to follow up."""


async def build_context(
    phone: str,
    agent_persona: str = _BASE_PERSONA,
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

    crm_section = _build_crm_section(contact)
    system_prompt = _assemble_prompt(agent_persona, crm_section, extra_instructions)

    logger.info(
        "Context built",
        extra={
            "phone": phone,
            "contact_found": contact is not None,
            "contact_id": contact.get("id") if contact else None,
        },
    )
    return system_prompt, contact


def _build_crm_section(contact: Optional[dict[str, Any]]) -> str:
    """Format CRM data into a readable context block for the LLM."""
    if not contact:
        return "CRM STATUS: This is a new caller with no existing record in the CRM."

    lines = ["CRM CONTEXT (use this to personalize the conversation):"]

    # Identity
    name_parts = [contact.get("firstName", ""), contact.get("lastName", "")]
    full_name = " ".join(p for p in name_parts if p).strip()
    if full_name:
        lines.append(f"  - Caller Name: {full_name}")
    if email := contact.get("email"):
        lines.append(f"  - Email: {email}")

    # Tags
    tags = contact.get("tags", [])
    if tags:
        lines.append(f"  - Tags: {', '.join(tags)}")

    # Notes (most recent 3)
    notes = contact.get("notes", [])
    if notes:
        lines.append("  - Recent Notes:")
        for note in notes[:3]:
            body = note.get("body", "").strip().replace("\n", " ")
            if body:
                lines.append(f"      • {body[:200]}")

    # Open opportunities
    opportunities = contact.get("opportunities", [])
    open_opps = [o for o in opportunities if o.get("status") == "open"]
    if open_opps:
        lines.append(f"  - Open Opportunities: {len(open_opps)}")
        for opp in open_opps[:2]:
            lines.append(f"      • {opp.get('name', 'Unnamed')} — ${opp.get('monetaryValue', 0):,.0f}")

    # Custom fields
    custom_fields = contact.get("customField", [])
    if custom_fields:
        lines.append("  - Custom Fields:")
        for field in custom_fields[:5]:
            key = field.get("id", "")
            val = field.get("value", "")
            if key and val:
                lines.append(f"      • {key}: {val}")

    return "\n".join(lines)


def _assemble_prompt(
    persona: str,
    crm_section: str,
    extra_instructions: str,
) -> str:
    parts = [persona.strip(), "", crm_section]
    if extra_instructions:
        parts += ["", "ADDITIONAL INSTRUCTIONS:", extra_instructions.strip()]
    parts += [
        "",
        "IMPORTANT: You have access to tools for booking appointments, sending SMS, "
        "adding tags, creating notes, and escalating calls. Use them when appropriate.",
    ]
    return "\n".join(parts)
