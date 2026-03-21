"""
TaskDeskr Voice Core — API Routes
====================================
FastAPI application factory and route definitions.

Endpoints:
  POST /vapi/webhook        — Main Vapi event receiver (all call lifecycle events)
  GET  /health              — Health check for Render/Railway uptime monitoring
  GET  /                    — Root info endpoint
"""

from __future__ import annotations

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from src.core.config import settings
from src.core.logger import get_logger
from src.api.webhooks import handle_vapi_event, verify_vapi_signature

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Application factory — creates and configures the FastAPI instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Production-ready voice backend for TaskDeskr: Vapi + OpenAI/Claude + GoHighLevel",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
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
        x_vapi_signature: Optional[str] = Header(default=None),
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
        """
        raw_body = await request.body()

        # Verify webhook signature if secret is configured
        if settings.VAPI_WEBHOOK_SECRET:
            if not verify_vapi_signature(raw_body, x_vapi_signature or ""):
                logger.warning("Invalid Vapi webhook signature — rejecting request")
                raise HTTPException(status_code=401, detail="Invalid webhook signature")

        try:
            payload = await request.json()
        except Exception:
            logger.error("Failed to parse webhook payload as JSON")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        response = await handle_vapi_event(payload)
        return JSONResponse(content=response)

    return app
