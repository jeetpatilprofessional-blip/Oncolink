from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.consent import router as consent_router
from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.database import close_db, init_db
from app.logging import logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager for startup and shutdown hooks."""
    settings: Settings = app.state.settings
    setup_logging(settings.log_level)
    logger.info("Starting ONCOLINK backend", extra={"project": settings.project_name})

    # Guard: In production, demo local email relaxation must never be enabled
    if settings.environment.lower() == "production" and settings.allow_demo_local_emails:
        raise RuntimeError(
            "Production environment must not enable demo local email validation relaxation "
            "(allow_demo_local_emails must be False when environment is production)."
        )

    # Initialize MongoDB (will raise RuntimeError and refuse to start if unreachable)
    await init_db(settings)

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

    if cfg.environment.lower() == "production" and cfg.allow_demo_local_emails:
        raise RuntimeError(
            "Production environment must not enable demo local email validation relaxation "
            "(allow_demo_local_emails must be False when environment is production)."
        )

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

    # Register Routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(consent_router)
    app.include_router(admin_router)

    return app


# Default app instance for ASGI servers (uvicorn)
app = create_app()
