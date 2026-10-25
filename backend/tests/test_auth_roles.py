from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.api.deps import require_role, require_verified_doctor
from app.config import Settings
from app.database import close_db, init_db
from app.main import create_app
from app.models.user import DoctorVerificationStatus, UserInDB, UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService

# --- TEST-ONLY ROUTER (MOUNTED ONLY IN TEST APP) ---
role_matrix_router = APIRouter(prefix="/test-only", tags=["Test-Only"])


@role_matrix_router.get("/patient-endpoint")
def patient_endpoint(user: Annotated[UserInDB, Depends(require_role(UserRole.PATIENT))]):
    return {"message": "patient_access_granted", "user": user.email}


@role_matrix_router.get("/screener-endpoint")
def screener_endpoint(user: Annotated[UserInDB, Depends(require_role(UserRole.SCREENER))]):
    return {"message": "screener_access_granted", "user": user.email}


@role_matrix_router.get("/doctor-endpoint")
def doctor_endpoint(user: Annotated[UserInDB, Depends(require_role(UserRole.DOCTOR))]):
    return {"message": "doctor_access_granted", "user": user.email}


@role_matrix_router.get("/coordinator-endpoint")
def coordinator_endpoint(user: Annotated[UserInDB, Depends(require_role(UserRole.HOSPITAL_COORDINATOR))]):
    return {"message": "coordinator_access_granted", "user": user.email}


@role_matrix_router.get("/admin-endpoint")
def admin_endpoint(user: Annotated[UserInDB, Depends(require_role(UserRole.ADMIN))]):
    return {"message": "admin_access_granted", "user": user.email}


@role_matrix_router.get("/verified-doctor-endpoint")
def verified_doctor_endpoint(user: Annotated[UserInDB, Depends(require_verified_doctor)]):
    return {"message": "verified_doctor_access_granted", "user": user.email}


@pytest.fixture
def app_with_test_router(test_settings: Settings) -> FastAPI:
    """App instance mounting the test-only router specifically for role matrix verification."""
    test_app = create_app(test_settings)
    test_app.include_router(role_matrix_router)
    return test_app


@pytest.fixture
async def role_test_client(
    app_with_test_router: FastAPI, test_settings: Settings
) -> AsyncGenerator[AsyncClient, None]:
    await init_db(test_settings)
    transport = ASGITransport(app=app_with_test_router)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await close_db()


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected_with_401(role_test_client: AsyncClient):
    """Unauthenticated requests to protected endpoints must return HTTP 401."""
    endpoints = [
        "/test-only/patient-endpoint",
        "/test-only/screener-endpoint",
        "/test-only/doctor-endpoint",
        "/test-only/coordinator-endpoint",
        "/test-only/admin-endpoint",
        "/test-only/verified-doctor-endpoint",
    ]
    for endpoint in endpoints:
        res = await role_test_client.get(endpoint)
        assert res.status_code == 401, f"Expected 401 on {endpoint}, got {res.status_code}"


@pytest.mark.asyncio
async def test_role_cross_matrix_enforcement(
    role_test_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Every role is denied on every other role's endpoints.
    Verifies the complete 5x5 matrix of role permissions.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)

    roles = [
        UserRole.PATIENT,
        UserRole.SCREENER,
        UserRole.DOCTOR,
        UserRole.HOSPITAL_COORDINATOR,
        UserRole.ADMIN,
    ]

    tokens_by_role: dict[UserRole, str] = {}

    for r in roles:
        doc = {
            "email": f"{r.value}@example.com",
            "password_hash": auth_service.hash_password("Password#123!"),
            "role": r.value,
            "is_active": True,
            "is_demo": False,
            "created_at": datetime.now(UTC),
            "failed_login_attempts": 0,
            "locked_until": None,
            "totp_enrolled": True,
            "registration_number": "DOC-123" if r == UserRole.DOCTOR else None,
            "verification_status": DoctorVerificationStatus.VERIFIED.value if r == UserRole.DOCTOR else None,
        }
        res = await db["users"].insert_one(doc)
        user_id = str(res.inserted_id)
        token, _ = auth_service.create_access_token(user_id=user_id, role=r.value)
        tokens_by_role[r] = token

    endpoints_by_role = {
        UserRole.PATIENT: "/test-only/patient-endpoint",
        UserRole.SCREENER: "/test-only/screener-endpoint",
        UserRole.DOCTOR: "/test-only/doctor-endpoint",
        UserRole.HOSPITAL_COORDINATOR: "/test-only/coordinator-endpoint",
        UserRole.ADMIN: "/test-only/admin-endpoint",
    }

    # Test the complete matrix
    for caller_role, token in tokens_by_role.items():
        headers = {"Authorization": f"Bearer {token}"}
        for target_role, endpoint in endpoints_by_role.items():
            res = await role_test_client.get(endpoint, headers=headers)
            if caller_role == target_role:
                assert res.status_code == 200, (
                    f"Role {caller_role} should access {endpoint}, got {res.status_code}: {res.text}"
                )
            else:
                assert res.status_code == 403, (
                    f"Role {caller_role} MUST be denied on {endpoint}, got {res.status_code}"
                )


@pytest.mark.asyncio
async def test_require_verified_doctor_blocks_unverified(
    role_test_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    require_verified_doctor rejects doctors whose verification_status is not 'verified'.
    Tests pending, rejected, and verified states, plus non-doctor roles.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)

    # 1. Doctor with pending verification
    pending_doc = {
        "email": "doctor_pending@example.com",
        "password_hash": auth_service.hash_password("Password#123!"),
        "role": UserRole.DOCTOR.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "registration_number": "DOC-PENDING",
        "verification_status": DoctorVerificationStatus.PENDING.value,
    }
    res_p = await db["users"].insert_one(pending_doc)
    pending_token, _ = auth_service.create_access_token(str(res_p.inserted_id), UserRole.DOCTOR.value)

    res = await role_test_client.get(
        "/test-only/verified-doctor-endpoint",
        headers={"Authorization": f"Bearer {pending_token}"},
    )
    assert res.status_code == 403
    assert "pending" in res.json()["detail"]

    # 2. Doctor with rejected verification
    rejected_doc = {
        "email": "doctor_rejected@example.com",
        "password_hash": auth_service.hash_password("Password#123!"),
        "role": UserRole.DOCTOR.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "registration_number": "DOC-REJECTED",
        "verification_status": DoctorVerificationStatus.REJECTED.value,
    }
    res_r = await db["users"].insert_one(rejected_doc)
    rejected_token, _ = auth_service.create_access_token(str(res_r.inserted_id), UserRole.DOCTOR.value)

    res = await role_test_client.get(
        "/test-only/verified-doctor-endpoint",
        headers={"Authorization": f"Bearer {rejected_token}"},
    )
    assert res.status_code == 403
    assert "rejected" in res.json()["detail"]

    # 3. Verified doctor
    verified_doc = {
        "email": "doctor_verified@example.com",
        "password_hash": auth_service.hash_password("Password#123!"),
        "role": UserRole.DOCTOR.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "registration_number": "DOC-VERIFIED",
        "verification_status": DoctorVerificationStatus.VERIFIED.value,
    }
    res_v = await db["users"].insert_one(verified_doc)
    verified_token, _ = auth_service.create_access_token(str(res_v.inserted_id), UserRole.DOCTOR.value)

    res = await role_test_client.get(
        "/test-only/verified-doctor-endpoint",
        headers={"Authorization": f"Bearer {verified_token}"},
    )
    assert res.status_code == 200
    assert res.json()["message"] == "verified_doctor_access_granted"
