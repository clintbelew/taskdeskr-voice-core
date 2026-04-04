"""
TaskDeskr Voice Core — API Routes
====================================
FastAPI application factory and route definitions.

Endpoints:
  POST /vapi/webhook        — Main Vapi event receiver (all call lifecycle events)
  GET  /health              — Health check for Render/Railway uptime monitoring
  GET  /                    — Root info endpoint

Keep-warm:
  A background task pings /health every 10 minutes so Render's free tier never
  goes cold. Render spins down after ~15 min of inactivity; Vapi only waits 20s
  for a webhook response — so a cold start = failed call.
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
    base_url = f"https://{settings.RENDER_EXTERNAL_HOSTNAME}" if getattr(settings, "RENDER_EXTERNAL_HOSTNAME", None) else "https://taskdeskr-voice-core.onrender.com"
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
    logger.info("Keep-warm background task started (interval: 10 min)")
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
        description="Production-ready voice backend for TaskDeskr: Vapi + Claude + GoHighLevel",
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

        Vapi sends all call lifecycle events here:
          - assistant-request
          - call-started
          - function-call
          - transcript
          - end-of-call-report
          - hang

        Configure this URL in your Vapi dashboard under:
        Dashboard → Phone Numbers → Server URL  (or Assistant → Server URL)

        Vapi authenticates by sending the secret as a plain-text value in the
        X-Vapi-Secret header (not HMAC). We do a constant-time comparison.
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

        response = await handle_vapi_event(payload)
        return JSONResponse(content=response)

    return app
