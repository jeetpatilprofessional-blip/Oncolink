import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint_structure(async_client: AsyncClient) -> None:
    """Test that GET /health returns expected status and separated service diagnostics."""
    response = await async_client.get("/health")
    # Endpoint should return JSON response with status and services
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "timestamp" in data
    assert "services" in data
    assert "mongodb" in data["services"]
    assert "minio" in data["services"]
    assert "status" in data["services"]["mongodb"]
    assert "status" in data["services"]["minio"]
