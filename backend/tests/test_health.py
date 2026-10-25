import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_structure(async_client: AsyncClient) -> None:
    """Test that GET /health returns expected status and separated MongoDB and GridFS diagnostics."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "timestamp" in data
    assert "services" in data
    assert "mongodb" in data["services"]
    assert "gridfs" in data["services"]
    assert data["services"]["mongodb"]["status"] == "connected"
    assert data["services"]["gridfs"]["status"] == "connected"
