"""
TaskDeskr Voice Core — Model Router
=====================================
Routes LLM requests to OpenAI (GPT-4o) or Anthropic (Claude) based on:
  1. An explicit `provider` override passed per-request
  2. The global DEFAULT_LLM_PROVIDER setting
  3. "auto" mode: Claude for summarization/analysis, GPT for everything else

Returns a unified response schema regardless of which provider handled the call,
so the rest of the system never needs to branch on provider.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import anthropic
import openai

from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)

# ── Lazy-initialized clients ──────────────────────────────────────────────────
_openai_client: Optional[openai.AsyncOpenAI] = None
_anthropic_client: Optional[anthropic.AsyncAnthropic] = None


def _openai() -> openai.AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


def _anthropic() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


# ── Provider resolution ───────────────────────────────────────────────────────
_COMPLEX_TASKS = {"summarize", "analyze", "reason", "plan", "extract"}


def resolve_provider(
    task_type: Optional[str] = None,
    override: Optional[str] = None,
) -> str:
    """Determine which LLM provider to use for this request."""
    if override in ("openai", "anthropic"):
        return override

    if settings.DEFAULT_LLM_PROVIDER != "auto":
        return settings.DEFAULT_LLM_PROVIDER

    # Auto-routing: complex reasoning → Claude, conversational → GPT
    if task_type and task_type.lower() in _COMPLEX_TASKS:
        return "anthropic"
    return "openai"


# ── Unified completion interface ──────────────────────────────────────────────
async def complete(
    messages: list[dict[str, str]],
    system_prompt: str = "",
    tools: Optional[list[dict[str, Any]]] = None,
    task_type: Optional[str] = None,
    provider_override: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """
    Route a chat completion request to the appropriate LLM.

    Parameters
    ----------
    messages        : Conversation history as [{"role": ..., "content": ...}]
    system_prompt   : System-level instruction injected before the conversation
    tools           : Tool/function definitions in OpenAI format
    task_type       : Hint for auto-routing ("book", "summarize", "respond", …)
    provider_override: Force "openai" or "anthropic"
    temperature     : Sampling temperature (lower = more deterministic)
    max_tokens      : Max tokens in the completion

    Returns
    -------
    {
        "provider"    : "openai" | "anthropic",
        "content"     : str,          # text response (may be empty if tool_calls present)
        "tool_calls"  : list | None,  # [{id, name, arguments}] or None
        "usage"       : {prompt_tokens, completion_tokens},
        "raw"         : dict,         # full provider response for debugging
    }
    """
    provider = resolve_provider(task_type=task_type, override=provider_override)
    logger.info(
        "Routing LLM completion",
        extra={"provider": provider, "task_type": task_type, "messages_count": len(messages)},
    )

    if provider == "openai":
        return await _complete_openai(messages, system_prompt, tools, temperature, max_tokens)
    return await _complete_anthropic(messages, system_prompt, tools, temperature, max_tokens)


# ── OpenAI backend ────────────────────────────────────────────────────────────
async def _complete_openai(
    messages: list[dict[str, str]],
    system_prompt: str,
    tools: Optional[list[dict[str, Any]]],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    full_messages: list[dict[str, Any]] = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    kwargs: dict[str, Any] = {
        "model": settings.OPENAI_MODEL,
        "messages": full_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    response = await _openai().chat.completions.create(**kwargs)
    choice = response.choices[0]

    tool_calls = None
    if choice.message.tool_calls:
        tool_calls = [
            {
                "id": tc.id,
                "name": tc.function.name,
                "arguments": tc.function.arguments,  # raw JSON string
            }
            for tc in choice.message.tool_calls
        ]

    return {
        "provider": "openai",
        "content": choice.message.content or "",
        "tool_calls": tool_calls,
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
        },
        "raw": response.model_dump(),
    }


# ── Anthropic backend ─────────────────────────────────────────────────────────
async def _complete_anthropic(
    messages: list[dict[str, str]],
    system_prompt: str,
    tools: Optional[list[dict[str, Any]]],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    # Convert OpenAI-style tool definitions to Anthropic format
    anthropic_tools = None
    if tools:
        anthropic_tools = [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters", {}),
            }
            for t in tools
        ]

    kwargs: dict[str, Any] = {
        "model": settings.ANTHROPIC_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    if anthropic_tools:
        kwargs["tools"] = anthropic_tools
        kwargs["tool_choice"] = {"type": "any"}  # Force Claude to use a tool

    response = await _anthropic().messages.create(**kwargs)

    content_text = ""
    tool_calls = None
    for block in response.content:
        if block.type == "text":
            content_text = block.text
        elif block.type == "tool_use":
            if tool_calls is None:
                tool_calls = []
            tool_calls.append(
                {
                    "id": block.id,
                    "name": block.name,
                    "arguments": json.dumps(block.input),
                }
            )

    return {
        "provider": "anthropic",
        "content": content_text,
        "tool_calls": tool_calls,
        "usage": {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
        },
        "raw": response.model_dump(),
    }
