import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.database import close_db, init_db
from app.main import create_app
from app.models.user import UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from tests.test_auth_roles import role_matrix_router


@pytest.mark.asyncio
async def test_temp_token_claims_and_expiration(test_settings: Settings, test_mongo_client: AsyncIOMotorClient):
    """
    Verifies that the temporary token carries scope='2fa_pending',
    type='2fa_pending', and expires within 300 seconds (5 minutes).
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)

    user_id = "507f1f77bcf86cd799439099"
    temp_token = auth_svc.create_temp_2fa_token(user_id=user_id, role="doctor")

    payload = auth_svc.decode_token(temp_token, expected_type="2fa_pending", expected_scope="2fa_pending")
    assert payload.sub == user_id
    assert payload.role == "doctor"
    assert payload.type == "2fa_pending"
    assert payload.scope == "2fa_pending"
    # Expires in 5 minutes (300s window)
    remaining_seconds = payload.exp - payload.iat
    assert 295 <= remaining_seconds <= 305


@pytest.mark.asyncio
async def test_temp_token_gets_401_on_auth_me_all_admin_routes_and_other_roles(
    test_settings: Settings, test_mongo_client: AsyncIOMotorClient
):
    """
    Temporary 2FA token MUST receive 401 Unauthorized on:
    - /auth/me
    - Every /admin route (GET /admin/users, POST /admin/users, POST /admin/doctors/{id}/verify, POST /admin/users/{id}/deactivate)
    - One route per other role (patient, screener, doctor, coordinator)
    """
    app = create_app(test_settings)
    app.include_router(role_matrix_router)

    await init_db(test_settings)
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)

    user_id = "507f1f77bcf86cd799439099"
    temp_token = auth_svc.create_temp_2fa_token(user_id=user_id, role="admin")

    headers = {"Authorization": f"Bearer {temp_token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. /auth/me
        res_me = await client.get("/auth/me", headers=headers)
        assert res_me.status_code == 401, f"Expected 401 on /auth/me, got {res_me.status_code}"

        # 2. Every /admin route
        admin_routes = [
            ("GET", "/admin/users", None),
            ("POST", "/admin/users", {"email": "test@example.com", "password": "Password123!", "role": "screener"}),
            ("POST", "/admin/doctors/507f1f77bcf86cd799439099/verify", {"status": "verified"}),
            ("POST", "/admin/users/507f1f77bcf86cd799439099/deactivate", None),
        ]
        for method, route, body in admin_routes:
            if method == "GET":
                res = await client.get(route, headers=headers)
            else:
                res = await client.post(route, headers=headers, json=body)
            assert res.status_code == 401, f"Expected 401 on {method} {route}, got {res.status_code}: {res.text}"

        # 3. One route per other role
        other_role_routes = [
            "/test-only/patient-endpoint",
            "/test-only/screener-endpoint",
            "/test-only/doctor-endpoint",
            "/test-only/coordinator-endpoint",
        ]
        for route in other_role_routes:
            res = await client.get(route, headers=headers)
            assert res.status_code == 401, f"Expected 401 on {route}, got {res.status_code}"

    await close_db()


@pytest.mark.asyncio
async def test_access_token_is_rejected_by_2fa_only_endpoints(
    test_settings: Settings, test_mongo_client: AsyncIOMotorClient
):
    """
    Normal access tokens must be rejected with 401 Unauthorized by all 2FA-only endpoints:
    - POST /auth/2fa/login (passing access token as temp_token)
    - POST /auth/2fa/setup (with Bearer access_token or x-temp-token=access_token)
    - POST /auth/2fa/verify-setup (with Bearer access_token or x-temp-token=access_token)
    """
    app = create_app(test_settings)
    await init_db(test_settings)

    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)

    doctor_id = "507f1f77bcf86cd799439088"
    await db["users"].delete_many({"_id": doctor_id})
    await db["users"].insert_one(
        {
            "_id": doctor_id,
            "email": "doctor@hospital.org",
            "password_hash": auth_svc.hash_password("DoctorPass10!"),
            "role": UserRole.DOCTOR.value,
            "is_active": True,
            "totp_enrolled": False,
        }
    )

    access_token, _ = auth_svc.create_access_token(user_id=doctor_id, role=UserRole.DOCTOR.value)
    access_headers = {"Authorization": f"Bearer {access_token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. POST /auth/2fa/login using access token instead of temp token
        res_login = await client.post(
            "/auth/2fa/login",
            json={"temp_token": access_token, "code": "123456"},
        )
        assert res_login.status_code == 401, f"Expected 401 on 2fa/login with access token, got {res_login.status_code}"
        assert "Invalid or expired 2FA session token" in res_login.json()["detail"]

        # 2. POST /auth/2fa/setup using Bearer access token
        res_setup = await client.post("/auth/2fa/setup", headers=access_headers)
        assert res_setup.status_code == 401, f"Expected 401 on 2fa/setup with access token, got {res_setup.status_code}"

        # 3. POST /auth/2fa/verify-setup using Bearer access token
        res_verify = await client.post(
            "/auth/2fa/verify-setup",
            headers=access_headers,
            json={"secret": "JBSWY3DPEHPK3PXP", "code": "123456"},
        )
        assert res_verify.status_code == 401, f"Expected 401 on 2fa/verify-setup with access token, got {res_verify.status_code}"

    await close_db()
