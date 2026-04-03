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
from src.api.webhooks import handle_vapi_event

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

    @app.get("/debug/ghl", tags=["Debug"])
    async def debug_ghl():
        """Temporary debug endpoint — shows GHL key prefix to verify env var."""
        import httpx
        key = settings.GHL_API_KEY
        # Test the key against GHL
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://services.leadconnectorhq.com/contacts/",
                    headers={"Authorization": f"Bearer {key}", "Version": "2021-07-28"},
                    params={"locationId": settings.GHL_LOCATION_ID, "limit": 1}
                )
            ghl_status = r.status_code
        except Exception as e:
            ghl_status = f"error: {e}"
        return {
            "ghl_key_prefix": key[:25] if key else "EMPTY",
            "ghl_key_length": len(key),
            "ghl_api_status": ghl_status,
            "location_id": settings.GHL_LOCATION_ID,
        }

    return app
