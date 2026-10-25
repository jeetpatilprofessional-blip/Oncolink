from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.models.audit import AuditEventType
from app.models.user import UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_passwords_stored_as_argon2_not_plaintext(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Proves passwords are encrypted with Argon2id and never stored as plain text."""
    db = test_mongo_client[test_settings.mongo_db_name]

    # Register patient
    payload = {
        "email": "argon2_test@example.com",
        "password": "SecurePassword123!",
        "date_of_birth": "1990-01-01",
        "consent_version": "v1",
        "consent_accepted": True,
    }
    res = await async_client.post("/auth/register", json=payload)
    assert res.status_code == 201

    # Check MongoDB document directly
    user_doc = await db["users"].find_one({"email": "argon2_test@example.com"})
    assert user_doc is not None
    assert "password" not in user_doc
    assert user_doc["password_hash"].startswith("$argon2id$")
    assert "SecurePassword123!" not in user_doc["password_hash"]


@pytest.mark.asyncio
async def test_password_policy_enforcement(async_client: AsyncClient):
    """Enforces min length 10 and rejects password equal to email."""
    # Too short (<10 chars)
    short_res = await async_client.post(
        "/auth/register",
        json={
            "email": "short@example.com",
            "password": "Short1!",
            "date_of_birth": "1990-01-01",
            "consent_version": "v1",
            "consent_accepted": True,
        },
    )
    assert short_res.status_code in (400, 422)

    # Password equal to email
    equal_res = await async_client.post(
        "/auth/register",
        json={
            "email": "same_as_password@example.com",
            "password": "same_as_password@example.com",
            "date_of_birth": "1990-01-01",
            "consent_version": "v1",
            "consent_accepted": True,
        },
    )
    assert equal_res.status_code == 400
    assert "equal" in equal_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_refresh_token_rotation_and_reuse_detection(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Refresh tokens are rotated on each use.
    If an old (already used) refresh token is replayed, the entire token family
    is revoked, an audit record is created, and the request is rejected with 401.
    """
    db = test_mongo_client[test_settings.mongo_db_name]

    # 1. Register a patient to get an initial session and refresh cookie
    reg_res = await async_client.post(
        "/auth/register",
        json={
            "email": "reuse_test@example.com",
            "password": "ValidPassword123!",
            "date_of_birth": "1990-01-01",
            "consent_version": "v1",
            "consent_accepted": True,
        },
    )
    assert reg_res.status_code == 201
    initial_cookie = reg_res.cookies.get("oncolink_refresh_token")
    assert initial_cookie is not None

    # Verify initial refresh token hash exists in MongoDB
    hashed_initial = AuthService.hash_refresh_token(initial_cookie)
    token_rec = await db["refresh_tokens"].find_one({"token_hash": hashed_initial})
    assert token_rec is not None
    assert token_rec["revoked"] is False
    family_id = token_rec["family_id"]

    # 2. Legitimate refresh: rotates token
    refresh_res_1 = await async_client.post(
        "/auth/refresh", headers={"Cookie": f"oncolink_refresh_token={initial_cookie}"}
    )
    assert refresh_res_1.status_code == 200
    new_cookie_1 = refresh_res_1.cookies.get("oncolink_refresh_token")
    assert new_cookie_1 is not None
    assert new_cookie_1 != initial_cookie

    # The initial token is now revoked
    old_rec = await db["refresh_tokens"].find_one({"token_hash": hashed_initial})
    assert old_rec["revoked"] is True

    # 3. Legitimate second refresh: rotates token again
    refresh_res_2 = await async_client.post(
        "/auth/refresh", headers={"Cookie": f"oncolink_refresh_token={new_cookie_1}"}
    )
    assert refresh_res_2.status_code == 200
    new_cookie_2 = refresh_res_2.cookies.get("oncolink_refresh_token")
    assert new_cookie_2 != new_cookie_1

    # 4. REUSE ATTACK: Attacker replays initial_cookie!
    attack_res = await async_client.post(
        "/auth/refresh", headers={"Cookie": f"oncolink_refresh_token={initial_cookie}"}
    )
    assert attack_res.status_code == 401
    assert "reuse" in attack_res.json()["detail"].lower()

    # 5. Proof of family revocation: Even new_cookie_2 should now be revoked!
    legit_res_after_attack = await async_client.post(
        "/auth/refresh", headers={"Cookie": f"oncolink_refresh_token={new_cookie_2}"}
    )
    assert legit_res_after_attack.status_code == 401

    # Check MongoDB: every token in family is revoked
    family_tokens = await db["refresh_tokens"].find({"family_id": family_id}).to_list(100)
    assert len(family_tokens) >= 3
    assert all(t["revoked"] is True for t in family_tokens)

    # Check audit log for REFRESH_REUSE event
    reuse_audit = await db["audit_log"].find_one({"event_type": AuditEventType.REFRESH_REUSE.value})
    assert reuse_audit is not None
    assert reuse_audit["details"]["family_id"] == family_id


@pytest.mark.asyncio
async def test_account_lockout_after_five_failed_logins(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    After 5 consecutive failed logins, the account is locked for 15 minutes.
    Subsequent login attempts—even with the correct password—are rejected.
    Unknown email and wrong password return the identical generic error message.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)
    auth_service = AuthService(db, test_settings, audit_service)

    # Create active user
    correct_password = "CorrectPassword123!"
    doc = {
        "email": "lockout_target@example.com",
        "password_hash": auth_service.hash_password(correct_password),
        "role": UserRole.PATIENT.value,
        "is_active": True,
        "created_at": datetime.now(UTC),
        "failed_login_attempts": 0,
        "locked_until": None,
    }
    await db["users"].insert_one(doc)

    # 1. Test unknown email and wrong password return IDENTICAL error
    unknown_res = await async_client.post(
        "/auth/login",
        json={"email": "nonexistent@example.com", "password": "WrongPassword1!"},
    )
    wrong_pwd_res = await async_client.post(
        "/auth/login",
        json={"email": "lockout_target@example.com", "password": "WrongPassword1!"},
    )
    assert unknown_res.status_code == 401
    assert wrong_pwd_res.status_code == 401
    assert unknown_res.json()["detail"] == wrong_pwd_res.json()["detail"]

    # 2. Perform 4 more failed logins (total 5)
    for _ in range(4):
        res = await async_client.post(
            "/auth/login",
            json={"email": "lockout_target@example.com", "password": "WrongPassword1!"},
        )
        assert res.status_code == 401

    # 3. Account must now be locked in database
    user_in_db = await db["users"].find_one({"email": "lockout_target@example.com"})
    assert user_in_db["failed_login_attempts"] >= 5
    assert user_in_db["locked_until"] is not None

    # Check lockout audit log
    lockout_audit = await db["audit_log"].find_one({"event_type": AuditEventType.LOCKOUT.value})
    assert lockout_audit is not None
    assert lockout_audit["target_user_id"] == str(user_in_db["_id"])

    # 4. Attempt login with CORRECT password while locked: MUST BE REJECTED
    correct_attempt_res = await async_client.post(
        "/auth/login",
        json={"email": "lockout_target@example.com", "password": correct_password},
    )
    assert correct_attempt_res.status_code == 401
    assert "locked" in correct_attempt_res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_immediate_rejection_upon_deactivation(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Proves that deactivation takes effect immediately on existing valid access tokens,
    because every request verifies the user's active status from the database.
    """
    db = test_mongo_client[test_settings.mongo_db_name]

    # Register patient
    reg_res = await async_client.post(
        "/auth/register",
        json={
            "email": "deactivate_test@example.com",
            "password": "Password#123!",
            "date_of_birth": "1990-01-01",
            "consent_version": "v1",
            "consent_accepted": True,
        },
    )
    access_token = reg_res.json()["access_token"]
    user_id = reg_res.json()["user_id"]

    # Deactivate directly in DB
    from bson import ObjectId

    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"is_active": False}})

    # Attempt to use the still-valid JWT: must fail with 403 Forbidden
    # (Testing on an authenticated endpoint, e.g. health details if admin, or /test-only)
    from app.services.audit_service import AuditService
    from app.services.auth_service import AuthService

    auth_service = AuthService(db, test_settings, AuditService(db))
    # Test through deps directly or an endpoint
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.deps import get_current_user

    with pytest.raises(Exception) as excinfo:
        await get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=access_token),
            db=db,
            auth_service=auth_service,
        )
    assert "inactive" in str(excinfo.value.detail).lower()


@pytest.mark.asyncio
async def test_auth_me_endpoint(async_client: AsyncClient, test_mongo_client: AsyncIOMotorClient, test_settings: Settings):
    """GET /auth/me returns current user profile when authenticated; returns 401 when unauthenticated."""
    # 1. Unauthenticated gets 401
    unauth = await async_client.get("/auth/me")
    assert unauth.status_code == 401

    # 2. Authenticated user receives profile
    reg_res = await async_client.post(
        "/auth/register",
        json={
            "email": "me_test@example.com",
            "password": "ValidPassword123!",
            "date_of_birth": "1990-01-01",
            "consent_version": "v1",
            "consent_accepted": True,
        },
    )
    assert reg_res.status_code == 201
    token = reg_res.json()["access_token"]
    user_id = reg_res.json()["user_id"]

    me_res = await async_client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["id"] == user_id
    assert me_data["email"] == "me_test@example.com"
    assert me_data["role"] == "patient"
    assert me_data["is_active"] is True
    assert me_data["is_demo"] is False
    assert me_data["totp_enrolled"] is False


@pytest.mark.asyncio
async def test_cors_exact_origin(async_client: AsyncClient):
    """CORS middleware returns allow-credentials and exact origin from environment."""
    res = await async_client.get(
        "/health",
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert res.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
    assert res.headers.get("access-control-allow-credentials") == "true"
