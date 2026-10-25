from datetime import UTC, datetime

import pytest
from bson import ObjectId
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import ValidationError

from app.config import Settings
from app.database import close_db, init_db
from app.main import create_app
from app.models.token import LoginRequest
from app.models.user import PatientRegisterRequest, StaffUserCreate, UserRole
from app.models.validators import validate_oncolink_email
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService


def test_email_validation_in_dev_test_mode(monkeypatch, test_settings: Settings):
    """Proves that .local demo addresses validate in development and test environments."""
    # Settings default is test in test suite
    email = "demo.patient@oncolink.local"
    validated = validate_oncolink_email(email)
    assert validated == "demo.patient@oncolink.local"

    # Validates across all request models
    login = LoginRequest(email=email, password="ValidPassword10!")
    assert login.email == email

    register = PatientRegisterRequest(
        email=email,
        password="ValidPassword10!",
        date_of_birth="1990-01-01",
        consent_version="v1",
        consent_accepted=True,
    )
    assert register.email == email

    staff = StaffUserCreate(
        email="demo.doctor@oncolink.local",
        password="ValidPassword10!",
        role=UserRole.DOCTOR,
    )
    assert staff.email == "demo.doctor@oncolink.local"


def test_production_mode_refuses_to_start_with_relaxed_validation(test_settings: Settings):
    """
    Security invariant: If ENV=production and relaxation is on (allow_demo_local_emails=True),
    the application MUST refuse to start with RuntimeError.
    """
    prod_invalid_settings = Settings(
        project_name="OncoLink-Prod",
        environment="production",
        allow_demo_local_emails=True,
        mongo_uri=test_settings.mongo_uri,
        mongo_db_name="oncolink_prod_test",
        jwt_secret="prod_secret_key_that_is_at_least_32_bytes_long_for_security!",
        totp_encryption_key="mO4YZOqlOWz_0Q2XD5Da5sfoL6n13xlA8PRLnvpI3Q8=",
    )

    with pytest.raises(RuntimeError, match="Production environment must not enable demo local email validation"):
        create_app(prod_invalid_settings)


def test_email_model_validation_rejects_local_in_production(monkeypatch):
    """Model-level validation strictly rejects .local addresses when in production mode."""
    prod_settings = Settings(
        project_name="OncoLink-Prod",
        environment="production",
        allow_demo_local_emails=False,
        mongo_uri="mongodb://localhost:27017/dummy",
        jwt_secret="prod_secret_key_that_is_at_least_32_bytes_long_for_security!",
        totp_encryption_key="mO4YZOqlOWz_0Q2XD5Da5sfoL6n13xlA8PRLnvpI3Q8=",
    )
    monkeypatch.setattr("app.models.validators.get_settings", lambda: prod_settings)

    with pytest.raises(ValidationError) as exc:
        PatientRegisterRequest(
            email="demo.patient@oncolink.local",
            password="ValidPassword10!",
            consent_version="v1",
            consent_accepted=True,
        )
    assert "special-use or reserved name" in str(exc.value)


@pytest.mark.asyncio
async def test_production_rejects_local_email_at_registration_and_admin_staff_creation(
    test_mongo_client: AsyncIOMotorClient, test_settings: Settings, monkeypatch
):
    """
    Integration test: When running in production (with allow_demo_local_emails=False),
    a .local email address is strictly rejected (HTTP 422) at:
    1. Patient registration (POST /auth/register)
    2. Admin staff creation (POST /admin/users)
    """
    prod_settings = Settings(
        project_name="OncoLink-Prod",
        environment="production",
        allow_demo_local_emails=False,
        mongo_uri=test_settings.mongo_uri,
        mongo_db_name=test_settings.mongo_db_name,
        jwt_secret=test_settings.jwt_secret,
        totp_encryption_key=test_settings.totp_encryption_key,
    )
    monkeypatch.setattr("app.models.validators.get_settings", lambda: prod_settings)

    prod_app = create_app(prod_settings)
    try:
        await init_db(prod_settings)

        # Provision an active admin user for the staff creation test
        db = test_mongo_client[test_settings.mongo_db_name]
        audit_svc = AuditService(db)
        auth_svc = AuthService(db, prod_settings, audit_svc)
        admin_id = "507f1f77bcf86cd799439011"
        await db["users"].delete_many({"email": "admin@production-hospital.org"})
        await db["users"].insert_one(
            {
                "_id": ObjectId(admin_id),
                "email": "admin@production-hospital.org",
                "password_hash": auth_svc.hash_password("AdminSecurePassword10!"),
                "role": UserRole.ADMIN.value,
                "is_active": True,
                "is_demo": False,
                "created_at": datetime.now(UTC),
                "totp_enrolled": True,
            }
        )
        admin_token, _ = auth_svc.create_access_token(user_id=admin_id, role=UserRole.ADMIN.value)

        async with AsyncClient(
            transport=ASGITransport(app=prod_app),
            base_url="http://testserver",
        ) as client:
            # 1. Patient registration with .local is rejected
            res_reg = await client.post(
                "/auth/register",
                json={
                    "email": "demo.patient@oncolink.local",
                    "password": "ValidPassword10!",
                    "date_of_birth": "1990-01-01",
                    "consent_version": "v1",
                    "consent_accepted": True,
                },
            )
            assert res_reg.status_code == 422, f"Expected 422, got {res_reg.status_code}: {res_reg.text}"

            # 2. Admin staff creation with .local is rejected
            res_staff = await client.post(
                "/admin/users",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "email": "demo.screener@oncolink.local",
                    "password": "ValidPassword10!",
                    "role": "screener",
                },
            )
            assert res_staff.status_code == 422, f"Expected 422, got {res_staff.status_code}: {res_staff.text}"

            # 3. Legitimate production email address succeeds
            res_valid = await client.post(
                "/auth/register",
                json={
                    "email": "real.patient@production-hospital.org",
                    "password": "ValidPassword10!",
                    "date_of_birth": "1990-01-01",
                    "consent_version": "v1",
                    "consent_accepted": True,
                },
            )
            assert res_valid.status_code == 201
    finally:
        await close_db()
