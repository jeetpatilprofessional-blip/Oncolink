from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Response, status

from app.database import check_mongodb_health
from app.storage import check_gridfs_health

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(response: Response) -> dict[str, Any]:
    """
    Diagnostic health check endpoint verifying MongoDB and GridFS independently.
    Returns HTTP 200 when both are healthy; returns HTTP 503 if any service fails.
    """
    mongo_health = await check_mongodb_health()
    gridfs_health = await check_gridfs_health()

    is_healthy = mongo_health.get("status") == "connected" and gridfs_health.get("status") == "connected"

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "services": {
            "mongodb": mongo_health,
            "gridfs": gridfs_health,
        },
    }
