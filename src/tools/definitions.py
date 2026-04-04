"""
TaskDeskr Voice Core — Tool Definitions
========================================
These are the tools the LLM can call during a live Vapi conversation.
Defined in OpenAI function-calling format with Vapi server URL.

Tools (6 total):
  1. save_caller_info         — capture name and basic info
  2. save_lead_info           — save interest level, questions, use case
  3. create_lead_opportunity  — open a deal in the Voice Bot Pipeline
  4. send_website_link        — SMS the caller taskdeskr.com
  5. send_demo_booking_link   — SMS the caller a demo calendar booking link
  6. end_call                 — gracefully close the call

Design principles:
  - Tools are named for business outcomes, not technical operations.
  - Parameters are minimal — only what the AI can realistically collect.
  - Every tool includes a server.url so Vapi knows where to POST function-call events.
"""

from typing import Any

# The Vapi webhook endpoint — tools must include this so Vapi knows where to POST function-call events.
# Without this, Vapi silently returns "No result returned" for every tool call.
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

    # ── 4. Send website link via SMS ──────────────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "send_website_link",
            "description": (
                "Send the caller a text message with the TaskDeskr website link (taskdeskr.com). "
                "Use this when the caller wants to learn more at their own pace. "
                "Tell the caller: 'I'll text you the website link right now.'"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },

    # ── 5. Send demo booking link via SMS ─────────────────────────────────────
    {
        "type": "function",
        "server": {"url": VAPI_WEBHOOK_URL},
        "function": {
            "name": "send_demo_booking_link",
            "description": (
                "Send the caller a text message with a link to book a demo call with the TaskDeskr team. "
                "Use this when the caller wants to schedule a demo or speak with someone from the team. "
                "Tell the caller: 'I'll text you a link to book a demo call with our team.'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred_time": {
                        "type": "string",
                        "description": "If the caller mentioned a preferred time or day for the demo (optional)",
                    },
                },
                "required": [],
            },
        },
    },

    # ── 6. End call ───────────────────────────────────────────────────────────
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
