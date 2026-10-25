import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.cli import create_admin, seed_demo_users
from app.config import Settings
from app.models.audit import AuditEventType
from app.models.user import DoctorVerificationStatus, UserRole


@pytest.mark.asyncio
async def test_seed_demo_users_creates_all_roles(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Verifies that seed_demo_users creates one account for each of the 5 roles,
    marks them is_demo=True, verifies the doctor, and records patient consent.
    """
    db = test_mongo_client[test_settings.mongo_db_name]

    # Patch get_settings to return test_settings
    monkeypatch.setattr("app.cli.get_settings", lambda: test_settings)

    # Run seeder
    await seed_demo_users()

    # Verify each role was created
    expected_roles = [
        UserRole.PATIENT,
        UserRole.SCREENER,
        UserRole.DOCTOR,
        UserRole.HOSPITAL_COORDINATOR,
        UserRole.ADMIN,
    ]

    for role in expected_roles:
        user = await db["users"].find_one({"role": role.value, "is_demo": True})
        assert user is not None, f"Expected demo user for role {role.value} to exist"
        assert user["is_active"] is True
        assert user["is_demo"] is True
        assert "password_hash" in user
        assert user["password_hash"].startswith("$argon2id$")

    # Verify doctor specifics
    doctor = await db["users"].find_one({"role": UserRole.DOCTOR.value})
    assert doctor["verification_status"] == DoctorVerificationStatus.VERIFIED.value
    assert doctor["registration_number"] is not None

    # Verify patient consent record
    patient = await db["users"].find_one({"role": UserRole.PATIENT.value})
    consent = await db["consents"].find_one({"user_id": str(patient["_id"])})
    assert consent is not None
    assert consent["version"] == "v1"


@pytest.mark.asyncio
async def test_seed_demo_users_refuses_production(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    """Seeding must immediately abort if ENVIRONMENT or ENV is 'production'."""
    prod_settings = test_settings.model_copy(update={"environment": "production"})
    monkeypatch.setattr("app.cli.get_settings", lambda: prod_settings)

    with pytest.raises(SystemExit) as exc:
        await seed_demo_users()
    assert exc.value.code == 1


@pytest.mark.asyncio
async def test_seed_demo_users_refuses_missing_or_shared_passwords(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    """Seeding must abort if any credential is missing or passwords are shared."""
    # 1. Missing password
    missing_settings = test_settings.model_copy(update={"demo_admin_password": None})
    monkeypatch.setattr("app.cli.get_settings", lambda: missing_settings)

    with pytest.raises(SystemExit) as exc:
        await seed_demo_users()
    assert exc.value.code == 1

    # 2. Shared passwords across accounts
    shared_settings = test_settings.model_copy(
        update={
            "demo_patient_password": "SharedPassword123!",
            "demo_screener_password": "SharedPassword123!",
        }
    )
    monkeypatch.setattr("app.cli.get_settings", lambda: shared_settings)

    with pytest.raises(SystemExit) as exc:
        await seed_demo_users()
    assert exc.value.code == 1


@pytest.mark.asyncio
async def test_create_admin_cli(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Verifies that create_admin creates a real, non-demo admin account,
    enforces password policies and uniqueness, and writes an audit log.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    monkeypatch.setattr("app.cli.get_settings", lambda: test_settings)

    admin_email = "real.admin@hospital.org"
    admin_password = "RealAdminPassword2026!"

    # 1. Successful creation
    await create_admin(admin_email, admin_password)

    user = await db["users"].find_one({"email": admin_email})
    assert user is not None
    assert user["role"] == UserRole.ADMIN.value
    assert user["is_active"] is True
    assert user["is_demo"] is False
    assert user["totp_enrolled"] is False
    assert user["password_hash"].startswith("$argon2id$")

    # Verify audit log
    audit_entry = await db["audit_log"].find_one({
        "event_type": AuditEventType.USER_CREATION.value,
        "details.email": admin_email,
    })
    assert audit_entry is not None
    assert audit_entry["details"]["is_demo"] is False

    # 2. Refuses duplicate email
    with pytest.raises(SystemExit) as exc1:
        await create_admin(admin_email, "AnotherPassword123!")
    assert exc1.value.code == 1

    # 3. Refuses weak password (<10 chars)
    with pytest.raises(SystemExit) as exc2:
        await create_admin("another.admin@hospital.org", "Short1!")
    assert exc2.value.code == 1
