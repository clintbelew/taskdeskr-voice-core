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

    # ── 2. Save lead info (interest, questions, use case) ─────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "save_lead_info",
            "description": (
                "Save information about the caller's interest in TaskDeskr. "
                "Call this after you understand what they are looking for and "
                "what questions they asked. Only include fields you have actually collected."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "interest_level": {
                        "type": "string",
                        "enum": ["high", "medium", "low", "just_browsing"],
                        "description": "How interested the caller seemed in TaskDeskr",
                    },
                    "business_type": {
                        "type": "string",
                        "description": (
                            "Type of business the caller runs or works at "
                            "(e.g. 'medical office', 'law firm', 'real estate agency')"
                        ),
                    },
                    "main_question": {
                        "type": "string",
                        "description": "The main question or concern the caller had about TaskDeskr",
                    },
                    "referral_source": {
                        "type": "string",
                        "description": "How the caller heard about TaskDeskr (e.g. 'Google', 'friend referral', 'social media')",
                    },
                    "demo_requested": {
                        "type": "boolean",
                        "description": "Whether the caller asked for or agreed to a live demo",
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

    # ── 8. End call ───────────────────────────────────────────────────────────
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
