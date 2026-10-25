import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.models.audit import AuditEventType
from app.services.audit_service import AuditService


def test_audit_service_exposes_no_update_or_delete_methods():
    """
    Guarantees that AuditService provides strictly append-only functionality
    and purposefully exposes NO update or delete methods.
    """
    forbidden_terms = [
        "update",
        "update_one",
        "update_many",
        "delete",
        "delete_one",
        "delete_many",
        "remove",
        "drop",
        "modify",
        "replace",
        "replace_one",
    ]

    all_methods = [method for method in dir(AuditService) if not method.startswith("__")]

    for forbidden in forbidden_terms:
        assert forbidden not in all_methods, f"AuditService must not expose '{forbidden}' method!"
        assert not hasattr(AuditService, forbidden), f"AuditService must not have attribute '{forbidden}'!"

    # Verify allowed methods exist
    assert hasattr(AuditService, "insert")
    assert hasattr(AuditService, "get_logs")
    assert hasattr(AuditService, "get_by_user")


@pytest.mark.asyncio
async def test_audit_service_never_persists_secrets(
    test_mongo_client: AsyncIOMotorClient, test_settings: Settings
):
    """
    Verifies that AuditService strictly sanitizes any sensitive credentials
    (passwords, tokens, TOTP secrets, recovery codes) even if mistakenly passed in details.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)

    # Attempt to insert an audit entry containing forbidden secret keys
    tainted_details = {
        "user_email": "patient@example.com",
        "password": "SuperSecretPassword123!",
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$fakehash",
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret",
        "access_token": "secret_access_jwt",
        "refresh_token": "secret_refresh_token_value",
        "totp_secret": "JBSWY3DPEHPK3PXP",
        "recovery_codes": ["ABCD-1234", "EFGH-5678"],
        "metadata": {
            "nested_password": "nested_secret",
            "allowed_key": "safe_clinical_info",
        },
        "safe_flag": True,
    }

    entry_id = await audit_service.insert(
        event_type=AuditEventType.LOGIN_SUCCESS,
        actor_id="user_123",
        actor_role="patient",
        target_user_id="user_123",
        details=tainted_details,
    )

    # Read document directly from MongoDB
    from bson import ObjectId

    doc = await db["audit_log"].find_one({"_id": ObjectId(entry_id)})
    assert doc is not None

    stored_details = doc["details"]

    # Verify secrets were stripped
    assert "password" not in stored_details
    assert "password_hash" not in stored_details
    assert "token" not in stored_details
    assert "access_token" not in stored_details
    assert "refresh_token" not in stored_details
    assert "totp_secret" not in stored_details
    assert "recovery_codes" not in stored_details

    # Verify nested secrets were stripped
    assert "nested_password" not in stored_details["metadata"]

    # Verify safe data remains
    assert stored_details["user_email"] == "patient@example.com"
    assert stored_details["metadata"]["allowed_key"] == "safe_clinical_info"
    assert stored_details["safe_flag"] is True


@pytest.mark.asyncio
async def test_audit_service_read_methods(
    test_mongo_client: AsyncIOMotorClient, test_settings: Settings
):
    """Verifies get_logs and get_by_user read methods."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_service = AuditService(db)

    await audit_service.insert(
        event_type=AuditEventType.USER_CREATION,
        actor_id="admin_1",
        target_user_id="user_456",
        details={"info": "created"},
    )
    await audit_service.insert(
        event_type=AuditEventType.DEACTIVATION,
        actor_id="admin_1",
        target_user_id="user_456",
        details={"info": "deactivated"},
    )

    all_logs = await audit_service.get_logs(limit=10)
    assert len(all_logs) == 2

    user_logs = await audit_service.get_by_user("user_456")
    assert len(user_logs) == 2
    assert user_logs[0].event_type == AuditEventType.DEACTIVATION.value
