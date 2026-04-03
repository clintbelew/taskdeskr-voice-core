"""
TaskDeskr Voice Core — Phase 1 Tool Definitions
================================================
These are the tools the LLM can call during a live Vapi conversation.
Defined in OpenAI function-calling format.

Phase 1 tools (5 total):
  1. save_caller_info        — capture name and basic info
  2. save_qualification_data — save insurance, complaint, referral source
  3. create_lead_opportunity — open a deal in the Voice Bot Pipeline
  4. send_booking_link       — move stage to Booking Link Sent
  5. end_call                — gracefully close the call

Design principles:
  - Tools are named for business outcomes, not technical operations.
  - Parameters are minimal — only what the AI can realistically collect.
  - No tool does more than one GHL operation (keeps errors isolated).
"""

from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [

    # ── 1. Save caller name and basic info ────────────────────────────────────
    {
        "type": "function",
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

    # ── 2. Save qualification data ────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "save_qualification_data",
            "description": (
                "Save lead qualification information collected during the call. "
                "Call this after gathering insurance status, chief complaint, "
                "or how they heard about the office. Only include fields you have "
                "actually collected — do not guess or fabricate values."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "insurance_status": {
                        "type": "string",
                        "description": "Does the caller have health insurance? E.g. 'Yes', 'No', 'Not sure'",
                    },
                    "insurance_provider": {
                        "type": "string",
                        "description": "Name of the caller's insurance provider (e.g. 'Blue Cross', 'Aetna')",
                    },
                    "chief_complaint": {
                        "type": "string",
                        "description": "Brief description of the caller's main symptom or reason for calling",
                    },
                    "referral_source": {
                        "type": "string",
                        "description": "How the caller heard about the office (e.g. 'Google', 'Friend referral')",
                    },
                    "question_or_concern": {
                        "type": "string",
                        "description": "Any specific question or concern the caller mentioned",
                    },
                },
                "required": [],
            },
        },
    },

    # ── 3. Create lead opportunity ────────────────────────────────────────────
    {
        "type": "function",
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
                            "Use format: 'Voice Bot Lead — [First Name] [Last Name]'"
                        ),
                    },
                },
                "required": ["opportunity_name"],
            },
        },
    },

    # ── 4. Send booking link (move to Booking Link Sent stage) ────────────────
    {
        "type": "function",
        "function": {
            "name": "send_booking_link",
            "description": (
                "Use this when the caller is interested in scheduling an appointment. "
                "This moves their pipeline stage to 'Booking Link Sent' so the team "
                "knows to follow up with a scheduling link. "
                "Tell the caller: 'I'll have our team send you a scheduling link by text shortly.'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "caller_interest_level": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "How interested the caller seemed in scheduling",
                    },
                },
                "required": ["caller_interest_level"],
            },
        },
    },

    # ── 5. End call ───────────────────────────────────────────────────────────
    {
        "type": "function",
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
                            "disqualified",
                        ],
                        "description": "Reason the call is ending",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]
