from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.models.audit import AuditEventType
from app.models.user import DoctorVerificationStatus, UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_admin_create_staff_user_and_audit(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Admin can create staff users (screener, doctor, coordinator). Writes audit log."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)

    # 1. Create admin user
    admin_doc = {
        "email": "admin@example.com",
        "password_hash": auth_service.hash_password("AdminPass123!"),
        "role": UserRole.ADMIN.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "totp_enrolled": True,
    }
    res_a = await db["users"].insert_one(admin_doc)
    admin_token, _ = auth_service.create_access_token(str(res_a.inserted_id), UserRole.ADMIN.value)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Admin creates a doctor
    doctor_payload = {
        "email": "dr.staff@example.com",
        "password": "DoctorPass123!",
        "role": "doctor",
        "registration_number": "MCI-2026-789",
    }
    create_res = await async_client.post("/admin/users", json=doctor_payload, headers=admin_headers)
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert created_data["email"] == "dr.staff@example.com"
    assert created_data["role"] == "doctor"
    assert created_data["registration_number"] == "MCI-2026-789"
    assert created_data["verification_status"] == DoctorVerificationStatus.PENDING.value

    # 3. Check audit log
    audit_entry = await db["audit_log"].find_one({"event_type": AuditEventType.USER_CREATION.value})
    assert audit_entry is not None
    assert audit_entry["actor_id"] == str(res_a.inserted_id)
    assert audit_entry["details"]["role"] == "doctor"


@pytest.mark.asyncio
async def test_admin_verify_doctor(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Admin verifies a pending doctor, updating status and logging audit entry."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)

    admin_doc = {
        "email": "verifier.admin@example.com",
        "password_hash": auth_service.hash_password("AdminPass123!"),
        "role": UserRole.ADMIN.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "totp_enrolled": True,
    }
    res_a = await db["users"].insert_one(admin_doc)
    admin_token, _ = auth_service.create_access_token(str(res_a.inserted_id), UserRole.ADMIN.value)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    doctor_doc = {
        "email": "pending.doc@example.com",
        "password_hash": auth_service.hash_password("DoctorPass123!"),
        "role": UserRole.DOCTOR.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "registration_number": "DCI-9999",
        "verification_status": DoctorVerificationStatus.PENDING.value,
    }
    res_d = await db["users"].insert_one(doctor_doc)
    doctor_id = str(res_d.inserted_id)

    # Admin verifies doctor
    verify_res = await async_client.post(
        f"/admin/doctors/{doctor_id}/verify",
        json={"status": "verified"},
        headers=admin_headers,
    )
    assert verify_res.status_code == 200
    verified_data = verify_res.json()
    assert verified_data["verification_status"] == "verified"
    assert verified_data["verified_by"] == str(res_a.inserted_id)
    assert verified_data["verified_at"] is not None

    # Check audit log
    audit_entry = await db["audit_log"].find_one({"event_type": AuditEventType.VERIFICATION_CHANGES.value})
    assert audit_entry is not None
    assert audit_entry["target_user_id"] == doctor_id
    assert audit_entry["details"]["status"] == "verified"


@pytest.mark.asyncio
async def test_admin_deactivate_user(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Admin deactivates a user, revoking sessions and logging audit entry."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)

    admin_doc = {
        "email": "deactivator.admin@example.com",
        "password_hash": auth_service.hash_password("AdminPass123!"),
        "role": UserRole.ADMIN.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "totp_enrolled": True,
    }
    res_a = await db["users"].insert_one(admin_doc)
    admin_token, _ = auth_service.create_access_token(str(res_a.inserted_id), UserRole.ADMIN.value)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    target_doc = {
        "email": "target.screener@example.com",
        "password_hash": auth_service.hash_password("ScreenerPass123!"),
        "role": UserRole.SCREENER.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
    }
    res_t = await db["users"].insert_one(target_doc)
    target_id = str(res_t.inserted_id)

    # Deactivate
    deact_res = await async_client.post(
        f"/admin/users/{target_id}/deactivate",
        headers=admin_headers,
    )
    assert deact_res.status_code == 200
    assert deact_res.json()["is_active"] is False

    # Check database
    updated = await db["users"].find_one({"_id": res_t.inserted_id})
    assert updated["is_active"] is False

    # Check audit log
    audit_entry = await db["audit_log"].find_one({"event_type": AuditEventType.DEACTIVATION.value})
    assert audit_entry is not None
    assert audit_entry["target_user_id"] == target_id


@pytest.mark.asyncio
async def test_non_admin_cannot_access_admin_endpoints(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Non-admin roles get 403 Forbidden on all admin endpoints."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)

    patient_doc = {
        "email": "normal.patient@example.com",
        "password_hash": auth_service.hash_password("PatientPass123!"),
        "role": UserRole.PATIENT.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
    }
    res_p = await db["users"].insert_one(patient_doc)
    patient_token, _ = auth_service.create_access_token(str(res_p.inserted_id), UserRole.PATIENT.value)
    patient_headers = {"Authorization": f"Bearer {patient_token}"}

    # Attempt to list users
    res = await async_client.get("/admin/users", headers=patient_headers)
    assert res.status_code == 403

    # Attempt to create user
    res2 = await async_client.post(
        "/admin/users",
        json={"email": "hacker@example.com", "password": "Password123!", "role": "screener"},
        headers=patient_headers,
    )
    assert res2.status_code == 403
