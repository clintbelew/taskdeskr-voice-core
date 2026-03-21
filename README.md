# TaskDeskr Voice Core

**Production-ready voice backend** connecting Vapi, OpenAI/Claude, and GoHighLevel.
Designed as the reusable foundation for TaskDeskr's AI voice system.

---

## What This Does

When a call comes in through Vapi:

1. **Identifies the caller** — looks up their phone number in GoHighLevel
2. **Builds context** — injects their CRM history (tags, notes, opportunities) into the AI's system prompt
3. **Responds intelligently** — routes to GPT-4o or Claude depending on task type
4. **Takes action** — executes real CRM operations (booking, tagging, notes, SMS, escalation) via tool calls
5. **Summarizes the call** — generates a structured summary and saves it back to GHL

---

## Architecture

```
┌─────────────┐     webhook      ┌──────────────────────────────────────────┐
│    Vapi     │ ───────────────► │          TaskDeskr Voice Core             │
│  (voice)    │ ◄─────────────── │                                          │
└─────────────┘   response/tools │  src/                                    │
                                 │  ├── api/                                │
                                 │  │   ├── routes.py    (FastAPI endpoints) │
                                 │  │   └── webhooks.py  (event handlers)   │
                                 │  ├── core/                               │
                                 │  │   ├── config.py    (env vars)         │
                                 │  │   ├── logger.py    (structured logs)  │
                                 │  │   └── router.py    (GPT/Claude router)│
                                 │  ├── services/                           │
                                 │  │   ├── ghl.py       (GHL API client)   │
                                 │  │   ├── context.py   (CRM context build)│
                                 │  │   └── summary.py   (call summarizer)  │
                                 │  └── tools/                              │
                                 │      ├── definitions.py (tool schemas)   │
                                 │      └── dispatcher.py  (tool executor)  │
                                 └──────────────────────────────────────────┘
                                          │                    │
                                          ▼                    ▼
                                   ┌──────────┐        ┌─────────────┐
                                   │ OpenAI / │        │GoHighLevel  │
                                   │  Claude  │        │    CRM      │
                                   └──────────┘        └─────────────┘
```

---

## File Structure

| Path | Purpose |
|---|---|
| `main.py` | Application entry point |
| `src/api/routes.py` | FastAPI app factory and HTTP endpoints |
| `src/api/webhooks.py` | Vapi event lifecycle handlers |
| `src/core/config.py` | All environment variable definitions |
| `src/core/logger.py` | Structured JSON logging with call-scoped context |
| `src/core/router.py` | Unified LLM router (OpenAI + Anthropic) |
| `src/services/ghl.py` | GoHighLevel API client (contacts, booking, tags, notes, SMS) |
| `src/services/context.py` | CRM context builder for system prompt injection |
| `src/services/summary.py` | Structured call summary generator |
| `src/tools/definitions.py` | LLM tool definitions (OpenAI function-calling format) |
| `src/tools/dispatcher.py` | Tool call executor — maps LLM requests to GHL actions |
| `tests/` | Unit tests (pytest) |

---

## Available Tools (AI Actions)

The AI agent can execute these actions during a live call:

| Tool | Description |
|---|---|
| `book_appointment` | Schedule a meeting in the GHL calendar |
| `add_contact_tag` | Tag the contact (e.g. `hot-lead`, `callback-requested`) |
| `remove_contact_tag` | Remove a tag from the contact |
| `add_contact_note` | Add a note to the contact's CRM timeline |
| `send_sms` | Send an outbound SMS via GoHighLevel |
| `escalate_to_human` | Transfer the call to a human agent |
| `end_call` | Gracefully end the call |
| `create_opportunity` | Open a pipeline deal in GHL |

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/clintbelew/taskdeskr-voice-core.git
cd taskdeskr-voice-core
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Run locally

```bash
python main.py
# Server starts on http://localhost:8000
```

### 4. Expose for local testing (optional)

```bash
# Using ngrok:
ngrok http 8000
# Use the ngrok URL as your Vapi Server URL
```

---

## Vapi Configuration

In your Vapi dashboard, set the **Server URL** to:

```
https://your-domain.com/vapi/webhook
```

This single endpoint handles all Vapi events (assistant-request, function-call, end-of-call-report, etc.).

---

## Deployment

### Render

```bash
# Option A: Use render.yaml (Infrastructure-as-Code)
# Push to GitHub → Connect repo in Render dashboard → Deploy

# Option B: Manual
# Build Command:  pip install -r requirements.txt
# Start Command:  uvicorn main:app --host 0.0.0.0 --port $PORT
# Health Check:   /health
```

### Railway

```bash
# railway.toml is pre-configured
railway up
```

Set all environment variables from `.env.example` in your platform's dashboard.

---

## Model Routing

Control which LLM handles requests via `DEFAULT_LLM_PROVIDER` in `.env`:

| Value | Behavior |
|---|---|
| `openai` | Always use GPT-4o |
| `anthropic` | Always use Claude |
| `auto` | GPT for conversations, Claude for summarization/analysis |

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Extending for Multi-Agent

To add a new agent (e.g. a sales agent, support agent):

1. Create a new context builder in `src/services/` with a custom persona
2. Add agent-specific tools to `src/tools/definitions.py`
3. Add a new route in `src/api/routes.py` (e.g. `/vapi/webhook/sales`)
4. The router, GHL service, and dispatcher are all reusable as-is

---

## Environment Variables Reference

See [`.env.example`](.env.example) for the full list with descriptions.

---

*Built by TaskDeskr — Voice AI infrastructure for modern businesses.*
