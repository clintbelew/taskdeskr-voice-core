"""
TaskDeskr Voice Core — Tool Definitions
=========================================
All tool/function definitions provided to the LLM in OpenAI function-calling format.
These are the actions the AI agent can request during a live call.

Tools:
  - book_appointment      : Schedule a meeting in GHL calendar
  - add_contact_tag       : Tag a contact (e.g. "hot-lead", "callback-requested")
  - remove_contact_tag    : Remove a tag from a contact
  - add_contact_note      : Add a note to the contact's timeline
  - send_sms              : Send an outbound SMS to the caller
  - escalate_to_human     : Transfer the call to a human agent
  - end_call              : Gracefully end the call
  - create_opportunity    : Open a pipeline deal in GHL
"""

from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Book an appointment for the caller in the GoHighLevel calendar. "
                "Use this when the caller wants to schedule a meeting, call, or consultation."
            ),
            "parameters": {
                "type": "object",
                "required": ["start_time"],
                "properties": {
                    "start_time": {
                        "type": "string",
                        "description": "ISO 8601 datetime string for the appointment start (e.g. '2026-04-01T14:00:00').",
                    },
                    "title": {
                        "type": "string",
                        "description": "Short title for the appointment. Defaults to 'Appointment'.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes to attach to the appointment.",
                    },
                    "calendar_id": {
                        "type": "string",
                        "description": "Override the default calendar ID if needed.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_contact_tag",
            "description": (
                "Add one or more tags to the caller's CRM contact record. "
                "Use tags like 'hot-lead', 'callback-requested', 'not-interested', 'vip'."
            ),
            "parameters": {
                "type": "object",
                "required": ["tags"],
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tag strings to add.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_contact_tag",
            "description": "Remove one or more tags from the caller's CRM contact record.",
            "parameters": {
                "type": "object",
                "required": ["tags"],
                "properties": {
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tag strings to remove.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_contact_note",
            "description": (
                "Add a note to the caller's CRM timeline. "
                "Use this to record important information shared during the call."
            ),
            "parameters": {
                "type": "object",
                "required": ["note"],
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "The note text to add to the contact record.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_sms",
            "description": (
                "Send an outbound SMS message to the caller via GoHighLevel. "
                "Use for confirmations, follow-ups, or links."
            ),
            "parameters": {
                "type": "object",
                "required": ["message"],
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The SMS message text to send.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "Transfer the call to a human agent. "
                "Use when the caller is frustrated, has a complex issue, or explicitly requests a human."
            ),
            "parameters": {
                "type": "object",
                "required": [],
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief reason for escalation (shown to the human agent).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_call",
            "description": (
                "Gracefully end the call after completing the interaction. "
                "Use when the caller's needs have been met and there is nothing more to do."
            ),
            "parameters": {
                "type": "object",
                "required": [],
                "properties": {
                    "farewell_message": {
                        "type": "string",
                        "description": "Optional closing message to say before hanging up.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_opportunity",
            "description": (
                "Create a new pipeline opportunity in GoHighLevel for this contact. "
                "Use when the caller is a qualified lead."
            ),
            "parameters": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the opportunity (e.g. 'Website Redesign — Acme Corp').",
                    },
                    "monetary_value": {
                        "type": "number",
                        "description": "Estimated deal value in USD.",
                    },
                    "stage_id": {
                        "type": "string",
                        "description": "Pipeline stage ID to place the opportunity in.",
                    },
                },
            },
        },
    },
]
