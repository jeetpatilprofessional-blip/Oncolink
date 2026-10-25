from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.database import close_db, init_db
from app.logging import logger, setup_logging
from app.storage import init_storage


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown hooks."""
    settings: Settings = app.state.settings
    setup_logging(settings.log_level)
    logger.info("Starting ONCOLINK backend", extra={"project": settings.project_name})

    # Initialize MongoDB (will raise RuntimeError and refuse to start if unreachable)
    await init_db(settings)

    # Initialize MinIO storage
    try:
        init_storage(settings)
    except Exception as exc:
        logger.warning("MinIO initialization warning during startup", extra={"error": str(exc)})

    yield

    # Shutdown hook
    await close_db()
    logger.info("ONCOLINK backend shutdown complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    Application factory for the ONCOLINK FastAPI backend.
    Enables custom configuration injection for testing and runtime deployment.
    """
    cfg = settings or get_settings()

    app = FastAPI(
        title="ONCOLINK API",
        description="Clinical Research & Education Prototype API for Oral Lesion Screening and Referral",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.settings = cfg

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health_router)

    return app


# Default app instance for ASGI servers (Uvicorn)
app = create_app()
