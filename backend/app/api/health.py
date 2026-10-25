from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import require_role
from app.database import check_mongodb_health
from app.models.user import UserInDB, UserRole
from app.storage import check_gridfs_health

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check(response: Response) -> dict[str, str]:
    """
    Public minimal health check endpoint.
    Returns HTTP 200 {"status": "healthy"} when operational;
    Returns HTTP 503 {"status": "unhealthy"} if core services are unreachable.
    """
    mongo_health = await check_mongodb_health()
    gridfs_health = await check_gridfs_health()

    is_healthy = mongo_health.get("status") == "connected" and gridfs_health.get("status") == "connected"

    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unhealthy"}

    return {"status": "healthy"}


@router.get("/health/details")
async def health_details(
    response: Response,
    _admin: Annotated[UserInDB, Depends(require_role(UserRole.ADMIN))],
) -> dict[str, Any]:
    """
    Detailed system health diagnostics for MongoDB and GridFS.
    Restricted strictly to administrators.
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
