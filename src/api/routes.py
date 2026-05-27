"""
TaskDeskr Voice Core — API Routes
====================================
FastAPI application factory and route definitions.

Endpoints:
  POST /vapi/webhook        — Main Vapi event receiver (all call lifecycle events)
  GET  /health              — Health check for Render/Railway uptime monitoring
  GET  /                    — Root info endpoint

Concurrency model:
  Every inbound POST /vapi/webhook is handled as a fully independent async request.
  FastAPI + Uvicorn (asyncio event loop) processes all requests concurrently — there
  is NO global lock, NO shared mutable state between calls, and NO request queue.

  Per-call state is isolated by call_id in Redis (or the in-memory fallback dict,
  which is also keyed by call_id and never shared across calls).

  The only module-level shared objects are:
    - _keep_warm_task: a background asyncio.Task (read-only after creation)
    - _memory_store in state.py: a dict[call_id -> state], safe because each
      call only reads/writes its own key

  This means N simultaneous callers each get their own isolated state bucket and
  their own independent async execution path through the webhook handler.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from src.core.config import settings
from src.core.logger import get_logger
from src.api.webhooks import handle_vapi_event

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Keep-warm background task
# ─────────────────────────────────────────────────────────────────────────────

_KEEP_WARM_INTERVAL = 10 * 60  # 10 minutes in seconds
_keep_warm_task: Optional[asyncio.Task] = None


async def _keep_warm_loop() -> None:
    """Ping our own /health endpoint every 10 minutes to prevent Render cold starts."""
    # Wait a bit after startup before the first ping
    await asyncio.sleep(60)
    base_url = (
        f"https://{settings.RENDER_EXTERNAL_HOSTNAME}"
        if getattr(settings, "RENDER_EXTERNAL_HOSTNAME", None)
        else "https://taskdeskr-voice-core.onrender.com"
    )
    url = f"{base_url}/health"
    while True:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
            logger.info("Keep-warm ping sent", extra={"status": resp.status_code, "url": url})
        except Exception as exc:
            logger.warning("Keep-warm ping failed", extra={"error": str(exc)})
        await asyncio.sleep(_KEEP_WARM_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start keep-warm background task on startup; cancel it on shutdown."""
    global _keep_warm_task
    _keep_warm_task = asyncio.create_task(_keep_warm_loop())
    logger.info(
        "TaskDeskr Voice Core started",
        extra={
            "version": settings.APP_VERSION,
            "concurrency_model": "per-request async isolation (no global locks)",
            "state_backend": "Redis (in-memory fallback if REDIS_URL not set)",
        },
    )
    try:
        yield
    finally:
        if _keep_warm_task and not _keep_warm_task.done():
            _keep_warm_task.cancel()
            try:
                await _keep_warm_task
            except asyncio.CancelledError:
                pass
        logger.info("Keep-warm background task stopped")


# ─────────────────────────────────────────────────────────────────────────────
# Application factory
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Application factory — creates and configures the FastAPI instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Production-ready voice backend for TaskDeskr: Vapi + Claude + GoHighLevel. "
            "Supports unlimited simultaneous inbound calls — each call is fully isolated "
            "by call_id with no shared mutable state."
        ),
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # CORS — restrict in production to your actual frontend/Vapi domains
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routes ────────────────────────────────────────────────────────────────

    @app.get("/", tags=["System"])
    async def root():
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
            "concurrency": "unlimited (async per-call isolation)",
        }

    @app.get("/health", tags=["System"])
    async def health():
        """
        Health check endpoint.
        Render and Railway poll this to determine if the service is alive.
        Returns 200 OK when the server is ready to accept requests.
        """
        return {"status": "healthy", "version": settings.APP_VERSION}

    @app.post("/vapi/webhook", tags=["Vapi"])
    async def vapi_webhook(
        request: Request,
        x_vapi_secret: Optional[str] = Header(default=None),
    ):
        """
        Main Vapi webhook endpoint.

        CONCURRENCY GUARANTEE:
        Each HTTP request to this endpoint is handled as a fully independent
        async coroutine by FastAPI/Uvicorn. There is no global lock, no queue,
        and no shared state between calls. Multiple simultaneous callers each
        get their own isolated execution path.

        State isolation is enforced by call_id:
          - Each call's data lives under its own Redis key (call:{call_id})
          - The in-memory fallback is also keyed by call_id
          - No call can read or write another call's state

        Vapi sends all call lifecycle events here:
          - assistant-request
          - call-started
          - function-call / tool-calls
          - transcript
          - end-of-call-report
          - hang

        Configure this URL in your Vapi dashboard under:
        Dashboard → Phone Numbers → Server URL  (or Assistant → Server URL)
        """
        raw_body = await request.body()

        # Verify webhook secret if configured (Vapi sends X-Vapi-Secret header)
        if settings.VAPI_WEBHOOK_SECRET:
            import hmac as _hmac
            received = (x_vapi_secret or "").encode()
            expected = settings.VAPI_WEBHOOK_SECRET.encode()
            if not _hmac.compare_digest(received, expected):
                logger.warning(
                    "Invalid Vapi webhook secret — rejecting request",
                    extra={"received_header": bool(x_vapi_secret)}
                )
                raise HTTPException(status_code=401, detail="Invalid webhook secret")

        try:
            payload = await request.json()
        except Exception:
            logger.error("Failed to parse webhook payload as JSON")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        # Each call to handle_vapi_event is fully independent:
        # - It reads call_id from the payload
        # - All state reads/writes are scoped to that call_id
        # - No global state is mutated
        response = await handle_vapi_event(payload)
        return JSONResponse(content=response)

    return app
