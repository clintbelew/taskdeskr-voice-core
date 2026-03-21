"""
TaskDeskr Voice Core — Entry Point
=====================================
Starts the FastAPI application via Uvicorn.

Usage:
  python main.py                    # Direct run (development)
  uvicorn main:app --host 0.0.0.0   # Production (used by Render/Railway via Procfile)
"""

import uvicorn
from src.core.config import settings
from src.core.logger import get_logger
from src.api.routes import create_app

logger = get_logger(__name__)

# Application instance (also referenced by Procfile: web: uvicorn main:app ...)
app = create_app()

if __name__ == "__main__":
    logger.info(
        "Starting TaskDeskr Voice Core",
        extra={"version": settings.APP_VERSION, "port": settings.PORT, "debug": settings.DEBUG},
    )
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="debug" if settings.DEBUG else "info",
        access_log=False,  # We handle our own structured logging
    )
