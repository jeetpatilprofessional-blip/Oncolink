from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response, status

from app.database import check_mongodb_health
from app.storage import check_minio_health

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(response: Response) -> dict[str, Any]:
    """
    Diagnostic health check endpoint verifying MongoDB and MinIO independently.
    Returns HTTP 200 when both are healthy; returns HTTP 503 if either service fails.
    """
    mongo_health = await check_mongodb_health()
    minio_health = check_minio_health()

    is_healthy = mongo_health.get("status") == "connected" and minio_health.get("status") == "connected"

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "services": {
            "mongodb": mongo_health,
            "minio": minio_health,
        },
    }
