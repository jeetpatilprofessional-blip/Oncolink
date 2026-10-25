from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.models.user import UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_public_health_endpoint_is_minimal(async_client: AsyncClient) -> None:
    """GET /health is public and minimal, returning only {"status": "healthy"}."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data == {"status": "healthy"}
    assert "services" not in data


@pytest.mark.asyncio
async def test_health_details_requires_admin(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
) -> None:
    """GET /health/details is admin-only and returns full MongoDB & GridFS diagnostic breakdown."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)

    # 1. Unauthenticated gets 401
    unauth_res = await async_client.get("/health/details")
    assert unauth_res.status_code == 401

    # 2. Non-admin gets 403
    patient_doc = {
        "email": "health.patient@example.com",
        "password_hash": auth_service.hash_password("Password#123!"),
        "role": UserRole.PATIENT.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
    }
    res_p = await db["users"].insert_one(patient_doc)
    patient_token, _ = auth_service.create_access_token(str(res_p.inserted_id), UserRole.PATIENT.value)

    forbidden_res = await async_client.get(
        "/health/details",
        headers={"Authorization": f"Bearer {patient_token}"},
    )
    assert forbidden_res.status_code == 403

    # 3. Admin gets 200 with complete diagnostics
    admin_doc = {
        "email": "health.admin@example.com",
        "password_hash": auth_service.hash_password("Password#123!"),
        "role": UserRole.ADMIN.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "totp_enrolled": True,
    }
    res_a = await db["users"].insert_one(admin_doc)
    admin_token, _ = auth_service.create_access_token(str(res_a.inserted_id), UserRole.ADMIN.value)

    admin_res = await async_client.get(
        "/health/details",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_res.status_code == 200
    details = admin_res.json()
    assert details["status"] == "healthy"
    assert "services" in details
    assert details["services"]["mongodb"]["status"] == "connected"
    assert details["services"]["gridfs"]["status"] == "connected"
