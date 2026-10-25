from datetime import UTC, datetime

import pyotp
import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.models.audit import AuditEventType
from app.models.user import DoctorVerificationStatus, UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.totp_service import TOTPService


@pytest.mark.asyncio
async def test_totp_mandatory_two_step_login_for_doctor(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    TOTP is mandatory for doctors and admins.
    Step 1 returns temp_token with requires_2fa=True.
    Step 2 verifies pyotp-generated 6-digit code.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)
    totp_service = TOTPService(test_settings.totp_encryption_key)

    # 1. Create doctor account in DB (already enrolled in TOTP)
    raw_secret = totp_service.generate_secret()
    encrypted_secret = totp_service.encrypt_secret(raw_secret)
    plain_recovery, hashed_recovery = totp_service.generate_recovery_codes(8)

    doctor_pwd = "DoctorPassword123!"
    doc = {
        "email": "dr.smith@example.com",
        "password_hash": auth_service.hash_password(doctor_pwd),
        "role": UserRole.DOCTOR.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "registration_number": "DCI-1001",
        "verification_status": DoctorVerificationStatus.VERIFIED.value,
        "totp_enrolled": True,
        "totp_secret_encrypted": encrypted_secret,
        "totp_recovery_codes_hashes": hashed_recovery,
    }
    await db["users"].insert_one(doc)

    # 2. Step 1: Login with password
    step1_res = await async_client.post(
        "/auth/login",
        json={"email": "dr.smith@example.com", "password": doctor_pwd},
    )
    assert step1_res.status_code == 200
    step1_data = step1_res.json()
    assert step1_data["requires_2fa"] is True
    assert step1_data["access_token"] == ""
    temp_token = step1_data["temp_token"]
    assert temp_token is not None

    # 3. Step 2: Attempt with invalid OTP code
    invalid_res = await async_client.post(
        "/auth/2fa/login",
        json={"temp_token": temp_token, "code": "000000"},
    )
    assert invalid_res.status_code == 401

    # 4. Step 2: Login with genuine pyotp-generated code
    valid_code = pyotp.TOTP(raw_secret).now()
    step2_res = await async_client.post(
        "/auth/2fa/login",
        json={"temp_token": temp_token, "code": valid_code},
    )
    assert step2_res.status_code == 200
    step2_data = step2_res.json()
    assert step2_data["requires_2fa"] is False
    assert step2_data["access_token"] != ""
    assert step2_data["role"] == "doctor"
    assert step2_res.cookies.get("oncolink_refresh_token") is not None


@pytest.mark.asyncio
async def test_totp_enrollment_and_secret_encryption_at_rest(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Unenrolled doctor or admin can access enrollment endpoints via temp_token.
    Confirms secret is encrypted at rest and 8 recovery codes are issued.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)
    totp_service = TOTPService(test_settings.totp_encryption_key)

    admin_pwd = "AdminPassword123!"
    doc = {
        "email": "new.admin@example.com",
        "password_hash": auth_service.hash_password(admin_pwd),
        "role": UserRole.ADMIN.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "totp_enrolled": False,
        "totp_secret_encrypted": None,
        "totp_recovery_codes_hashes": [],
    }
    await db["users"].insert_one(doc)

    # 1. Step 1: Login
    step1_res = await async_client.post(
        "/auth/login",
        json={"email": "new.admin@example.com", "password": admin_pwd},
    )
    temp_token = step1_res.json()["temp_token"]

    # 2. Setup 2FA
    setup_res = await async_client.post(
        "/auth/2fa/setup",
        headers={"x-temp-token": temp_token},
    )
    assert setup_res.status_code == 200
    setup_data = setup_res.json()
    secret = setup_data["secret"]
    assert "otpauth://" in setup_data["provisioning_uri"]

    # 3. Verify Setup using pyotp code
    code = pyotp.TOTP(secret).now()
    verify_res = await async_client.post(
        "/auth/2fa/verify-setup",
        headers={"x-temp-token": temp_token},
        json={"secret": secret, "code": code},
    )
    assert verify_res.status_code == 200
    verify_data = verify_res.json()
    assert verify_data["enrolled"] is True
    recovery_codes = verify_data["recovery_codes"]
    assert len(recovery_codes) == 8

    # 4. Verify MongoDB stored record: secret MUST be encrypted, not raw base32!
    user_in_db = await db["users"].find_one({"email": "new.admin@example.com"})
    assert user_in_db["totp_enrolled"] is True
    assert user_in_db["totp_secret_encrypted"] != secret
    # Decrypting stored secret must equal the raw secret
    decrypted = totp_service.decrypt_secret(user_in_db["totp_secret_encrypted"])
    assert decrypted == secret

    # Recovery codes stored as hashes, not plain
    assert len(user_in_db["totp_recovery_codes_hashes"]) == 8
    for plain_code in recovery_codes:
        assert plain_code not in user_in_db["totp_recovery_codes_hashes"]
        expected_hash = TOTPService.hash_recovery_code(plain_code)
        assert expected_hash in user_in_db["totp_recovery_codes_hashes"]

    # Check audit log
    enroll_audit = await db["audit_log"].find_one({"event_type": AuditEventType.TOTP_ENROLLMENT.value})
    assert enroll_audit is not None


@pytest.mark.asyncio
async def test_recovery_code_login_and_single_use_consumption(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Proves recovery codes work for 2FA login, are single-use,
    and cannot be reused after consumption.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)
    totp_service = TOTPService(test_settings.totp_encryption_key)

    raw_secret = totp_service.generate_secret()
    encrypted_secret = totp_service.encrypt_secret(raw_secret)
    plain_codes, hashed_codes = totp_service.generate_recovery_codes(8)

    doctor_pwd = "DoctorPassword123!"
    doc = {
        "email": "dr.recovery@example.com",
        "password_hash": auth_service.hash_password(doctor_pwd),
        "role": UserRole.DOCTOR.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "registration_number": "DCI-RECOVER",
        "verification_status": DoctorVerificationStatus.VERIFIED.value,
        "totp_enrolled": True,
        "totp_secret_encrypted": encrypted_secret,
        "totp_recovery_codes_hashes": hashed_codes,
    }
    await db["users"].insert_one(doc)

    code_to_use = plain_codes[0]

    # 1. Step 1 Login
    s1 = await async_client.post(
        "/auth/login",
        json={"email": "dr.recovery@example.com", "password": doctor_pwd},
    )
    temp_token = s1.json()["temp_token"]

    # 2. Step 2 Login with Recovery Code
    s2 = await async_client.post(
        "/auth/2fa/login",
        json={"temp_token": temp_token, "recovery_code": code_to_use},
    )
    assert s2.status_code == 200
    assert s2.json()["access_token"] != ""

    # 3. Check MongoDB: consumed recovery code hash must be removed (7 remaining)
    user_after = await db["users"].find_one({"email": "dr.recovery@example.com"})
    assert len(user_after["totp_recovery_codes_hashes"]) == 7
    assert TOTPService.hash_recovery_code(code_to_use) not in user_after["totp_recovery_codes_hashes"]

    # 4. Attempt to REUSE the same recovery code: must fail with 401
    s1_again = await async_client.post(
        "/auth/login",
        json={"email": "dr.recovery@example.com", "password": doctor_pwd},
    )
    temp_token_2 = s1_again.json()["temp_token"]

    reuse_attempt = await async_client.post(
        "/auth/2fa/login",
        json={"temp_token": temp_token_2, "recovery_code": code_to_use},
    )
    assert reuse_attempt.status_code == 401
