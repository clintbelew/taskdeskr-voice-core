"""
TaskDeskr Voice Core — Tool Definitions
========================================
These are the tools the LLM can call during a live Vapi conversation.
Defined in OpenAI function-calling format with Vapi server URL.

Tools (8 total):
  1. save_caller_info         — capture name and basic info
  2. save_lead_info           — save interest level, questions, use case
  3. create_lead_opportunity  — open a deal in the Voice Bot Pipeline
  4. check_availability       — fetch open calendar slots from GHL
  5. create_appointment       — book the selected slot directly in GHL
  6. send_website_link        — SMS the caller taskdeskr.com
  7. send_demo_booking_link   — SMS a booking link (fallback only)
  8. end_call                 — gracefully close the call

Design principles:
  - Tools are named for business outcomes, not technical operations.
  - Parameters are minimal — only what the AI can realistically collect.
  - Every tool includes a server.url so Vapi knows where to POST function-call events.
  - check_availability + create_appointment are the PRIMARY booking path.
  - send_demo_booking_link is FALLBACK only (caller explicitly says "text me a link").
"""

from typing import Any

# The Vapi webhook endpoint — tools must include this so Vapi knows where to POST function-call events.
VAPI_WEBHOOK_URL = "https://taskdeskr-voice-core.onrender.com/vapi/webhook"

TOOL_DEFINITIONS: list[dict[str, Any]] = [

    # ── 1. Save caller name and basic info ────────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "save_caller_info",
            "description": (
                "Save the caller's name (and optionally email) to their contact record. "
                "Call this as soon as you have confirmed the caller's first name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "first_name": {
                        "type": "string",
                        "description": "Caller's first name",
                    },
                    "last_name": {
                        "type": "string",
                        "description": "Caller's last name (if provided)",
                    },
                    "email": {
                        "type": "string",
                        "description": "Caller's email address (if provided)",
                    },
                },
                "required": ["first_name"],
            },
        },
    },

    # ── 2. Save qualification data (El Jefe intake fields) ───────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "save_qualification_data",
            "description": (
                "Save intake qualification information to the CRM. "
                "Call this after collecting the caller's chief complaint, insurance status, "
                "and referral source. Only include fields you have actually collected. "
                "All fields are optional — call this even if only one field is known."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "chief_complaint": {
                        "type": "string",
                        "description": (
                            "Brief description of the caller's legal matter or injury "
                            "(e.g. '18-wheeler accident on I-35, hospitalized with back injuries')"
                        ),
                    },
                    "has_insurance": {
                        "type": "boolean",
                        "description": "Whether the caller has insurance coverage related to the incident",
                    },
                    "insurance_provider": {
                        "type": "string",
                        "description": "Name of the caller's insurance provider, if known",
                    },
                    "referral_source": {
                        "type": "string",
                        "description": "How the caller heard about the law office (e.g. 'friend referral', 'Google', 'hospital staff')",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of tags to apply to this contact based on the intake. "
                            "Always include 'el-jefe-lead'. "
                            "Add 'personal-injury' for accident/injury/PI cases. "
                            "Add 'immigration' for immigration matters. "
                            "Add 'criminal' for criminal defense matters. "
                            "Add 'spanish-speaker' if the caller spoke Spanish at any point. "
                            "Add 'tier1-escalation', 'severe-injury', AND 'high-value-lead' "
                            "for hospitalized callers, surgery cases, or severe/critical injuries. "
                            "Add 'consultation-requested' if the caller asked for a consultation."
                        ),
                    },
                },
                "required": [],
            },
        },
    },

    # ── 3. Create lead opportunity ────────────────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "create_lead_opportunity",
            "description": (
                "Create a new opportunity in the Voice Bot Pipeline at the 'New Lead' stage. "
                "Call this once per call, after you have confirmed the caller's name. "
                "Do NOT call this multiple times for the same caller."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "opportunity_name": {
                        "type": "string",
                        "description": (
                            "Short descriptive name for the opportunity. "
                            "Use format: 'TaskDeskr Lead — [First Name] [Last Name]'"
                        ),
                    },
                },
                "required": ["opportunity_name"],
            },
        },
    },

    # ── 4. Check calendar availability ───────────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "check_availability",
            "description": (
                "Check available demo consultation time slots on the TaskDeskr calendar. "
                "Call this when the caller wants to book a demo or schedule a call with the team. "
                "Pass the caller's preferred date if they mentioned one, otherwise use tomorrow's date. "
                "This returns up to 6 available slots — read them aloud to the caller and ask which one works."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred_date": {
                        "type": "string",
                        "description": (
                            "The caller's preferred date in YYYY-MM-DD format. "
                            "If they said 'tomorrow', compute tomorrow's date. "
                            "If they said 'next Monday', compute that date. "
                            "If no preference, use tomorrow's date."
                        ),
                    },
                },
                "required": ["preferred_date"],
            },
        },
    },

    # ── 5. Create appointment (live booking) ──────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "create_appointment",
            "description": (
                "Book a demo consultation appointment directly in the GHL calendar. "
                "Call this ONLY after the caller has confirmed their chosen time slot. "
                "After booking, verbally confirm the date and time to the caller, "
                "then send them a confirmation SMS."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_iso": {
                        "type": "string",
                        "description": (
                            "The ISO datetime string of the selected slot, "
                            "exactly as returned by check_availability (e.g. '2026-04-07T10:00:00-05:00')."
                        ),
                    },
                    "caller_name": {
                        "type": "string",
                        "description": "Full name of the caller (first + last if available)",
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "Brief reason for the demo — what the caller wants to learn about or their business type. "
                            "Default: 'TaskDeskr Demo Consultation'"
                        ),
                    },
                },
                "required": ["slot_iso", "caller_name"],
            },
        },
    },

    # ── 6. Send website link via SMS ──────────────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "send_website_link",
            "description": (
                "Send the caller a text message with the TaskDeskr website link (taskdeskr.com). "
                "Use this when the caller wants to learn more at their own pace, "
                "or as a supplement after booking an appointment."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    # ── 7. Send demo booking link via SMS (FALLBACK ONLY) ─────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "send_demo_booking_link",
            "description": (
                "FALLBACK ONLY: Send the caller a text message with a link to self-schedule a demo. "
                "Use this ONLY if the caller explicitly says they want to choose a time later "
                "or if check_availability returns no available slots. "
                "The PRIMARY booking path is check_availability + create_appointment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred_time": {
                        "type": "string",
                        "description": "If the caller mentioned a preferred time or day (optional)",
                    },
                },
                "required": [],
            },
        },
    },


    # ── 8. Send SMS confirmation to caller ────────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "send_sms_confirmation",
            "description": (
                "Send a bilingual intake confirmation SMS to the caller after their information "
                "has been collected. Call this silently after save_qualification_data completes. "
                "Detects language automatically from the call context. "
                "For urgent/Tier 1 cases, set is_urgent=true for the escalation message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["english", "spanish"],
                        "description": "Language of the caller — english or spanish",
                    },
                    "matter_type": {
                        "type": "string",
                        "description": "The legal matter type (e.g. personal injury, immigration, criminal defense)",
                    },
                    "is_urgent": {
                        "type": "boolean",
                        "description": "True if this is a Tier 1 urgent escalation case",
                    },
                },
                "required": ["language"],
            },
        },
    },

    # ── 9. Send internal alert to attorney team ───────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "send_internal_alert",
            "description": (
                "Send an internal alert to the attorney team (Clint/Rudy) with the intake summary. "
                "Call this silently after save_qualification_data completes — never announce it. "
                "Include caller name, phone, matter type, urgency level, short summary, and callback expectation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "matter_type": {
                        "type": "string",
                        "description": "The legal matter type (e.g. personal injury, immigration, criminal defense)",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["standard", "urgent", "tier1"],
                        "description": "Urgency level of the case",
                    },
                    "summary": {
                        "type": "string",
                        "description": "1-2 sentence summary of the caller's situation",
                    },
                    "callback_eta": {
                        "type": "string",
                        "description": "Expected callback timeframe (e.g. 'within the hour', 'within 24 hours')",
                    },
                },
                "required": ["matter_type", "urgency"],
            },
        },
    },

    # ── 10. Create follow-up task ────────────────────────────────────────────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "create_follow_up_task",
            "description": (
                "Create a follow-up task in GHL for the attorney team. "
                "Call this silently after send_internal_alert completes. "
                "For urgent/Tier 1 cases: task_type='callback', urgency='tier1'. "
                "For consultation-requested cases: task_type='consultation', urgency='standard'. "
                "NEVER announce this to the caller."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {
                        "type": "string",
                        "enum": ["callback", "consultation"],
                        "description": "Type of follow-up task: callback for standard/urgent, consultation if caller requested a consult",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["standard", "urgent", "tier1"],
                        "description": "Urgency level of the task",
                    },
                    "matter_type": {
                        "type": "string",
                        "description": "The legal matter type (e.g. personal injury, immigration, criminal defense)",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional short notes for the task body (e.g. 'hospitalized, surgery scheduled')",
                    },
                },
                "required": ["task_type"],
            },
        },
    },

    # ── 11. End call ──────────────────────────────────────────────────────────────────────────────

    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "end_call",
            "description": (
                "End the call gracefully after you have completed the conversation. "
                "Use this when the caller says goodbye, has no more questions, "
                "or when the call has reached a natural conclusion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "enum": [
                            "completed",
                            "caller_requested",
                            "no_response",
                            "not_interested",
                        ],
                        "description": "Reason the call is ending",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]
