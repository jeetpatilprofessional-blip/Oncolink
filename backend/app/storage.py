from typing import Any

from minio import Minio

from app.config import Settings, get_settings
from app.logging import logger

_minio_client: Minio | None = None


def create_minio_client(settings: Settings | None = None) -> Minio:
    """Create a new Minio client instance."""
    cfg = settings or get_settings()
    return Minio(
        endpoint=cfg.minio_endpoint,
        access_key=cfg.minio_access_key,
        secret_key=cfg.minio_secret_key,
        secure=cfg.minio_use_ssl,
    )


def get_storage_client() -> Minio:
    """Get the active MinIO client."""
    global _minio_client
    if _minio_client is None:
        raise RuntimeError("MinIO client is not initialized.")
    return _minio_client


def init_storage(settings: Settings | None = None) -> Minio:
    """Initialize MinIO client and ensure the default bucket exists."""
    global _minio_client
    cfg = settings or get_settings()
    client = create_minio_client(cfg)
    try:
        if not client.bucket_exists(cfg.minio_bucket_name):
            client.make_bucket(cfg.minio_bucket_name)
            logger.info("Created MinIO bucket", extra={"bucket": cfg.minio_bucket_name})
        else:
            logger.info("MinIO bucket verified", extra={"bucket": cfg.minio_bucket_name})
    except Exception as exc:
        logger.warning(
            "Could not verify or create MinIO bucket during startup",
            extra={"error": str(exc)},
        )

    _minio_client = client
    return _minio_client


def check_minio_health(client: Minio | None = None) -> dict[str, Any]:
    """Check MinIO connectivity and verify bucket accessibility."""
    target_client = client or _minio_client
    cfg = get_settings()
    if target_client is None:
        return {"status": "disconnected", "error": "Client not initialized"}

    try:
        exists = target_client.bucket_exists(cfg.minio_bucket_name)
        return {
            "status": "connected",
            "bucket": cfg.minio_bucket_name,
            "bucket_exists": exists,
        }
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}
