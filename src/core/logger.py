"""
TaskDeskr Voice Core — Structured Logging Layer
================================================
Emits JSON log lines for compatibility with Render, Railway, Datadog, etc.
Supports per-call context injection via Python contextvars so every log line
from a given call automatically carries call_id and caller_phone.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

# ── Per-call context ──────────────────────────────────────────────────────────
_call_id_ctx: ContextVar[Optional[str]] = ContextVar("call_id", default=None)
_phone_ctx: ContextVar[Optional[str]] = ContextVar("phone", default=None)
_agent_ctx: ContextVar[Optional[str]] = ContextVar("agent", default=None)


def set_call_context(
    call_id: str,
    phone: Optional[str] = None,
    agent: Optional[str] = None,
) -> None:
    """Bind call metadata to the current async context."""
    _call_id_ctx.set(call_id)
    if phone:
        _phone_ctx.set(phone)
    if agent:
        _agent_ctx.set(agent)


def clear_call_context() -> None:
    _call_id_ctx.set(None)
    _phone_ctx.set(None)
    _agent_ctx.set(None)


# ── Formatter ─────────────────────────────────────────────────────────────────
class StructuredFormatter(logging.Formatter):
    """Renders log records as single-line JSON objects."""

    # Fields that belong to the LogRecord internals — we skip these when
    # copying extra fields to avoid noise.
    _SKIP_FIELDS = frozenset({
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "taskName",
    })

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Inject call-scoped context
        if call_id := _call_id_ctx.get():
            entry["call_id"] = call_id
        if phone := _phone_ctx.get():
            entry["phone"] = phone
        if agent := _agent_ctx.get():
            entry["agent"] = agent

        # Attach exception traceback if present
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        # Attach any caller-supplied extra fields
        for key, val in record.__dict__.items():
            if key not in self._SKIP_FIELDS and not key.startswith("_"):
                entry[key] = val

        return json.dumps(entry, default=str)


# ── Factory ───────────────────────────────────────────────────────────────────
def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    """Return a module-level structured logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger
