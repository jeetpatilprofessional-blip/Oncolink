from datetime import UTC, datetime
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import (
    get_audit_service,
    get_auth_service,
    get_client_ip,
    get_db,
    require_role,
)
from app.models.audit import AuditEventType
from app.models.user import (
    DoctorVerificationStatus,
    DoctorVerificationUpdate,
    StaffUserCreate,
    UserInDB,
    UserResponse,
    UserRole,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_staff_user(
    payload: StaffUserCreate,
    request: Request,
    current_admin: Annotated[UserInDB, Depends(require_role(UserRole.ADMIN))],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> UserResponse:
    """
    Creates a privileged staff user (screener, doctor, hospital_coordinator, admin).
    Restricted strictly to administrators.
    """
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    # 1. Validate password strength
    try:
        auth_service.validate_password_strength(payload.password, payload.email)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    # 2. Check existing account
    normalized_email = payload.email.strip().lower()
    existing = await db["users"].find_one({"email": normalized_email})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # 3. Create user document
    now = datetime.now(UTC)
    password_hash = auth_service.hash_password(payload.password)

    user_doc = {
        "email": normalized_email,
        "password_hash": password_hash,
        "role": payload.role.value,
        "is_active": True,
        "is_demo": False,
        "created_at": now,
        "failed_login_attempts": 0,
        "locked_until": None,
        "totp_enrolled": False,
        "totp_secret_encrypted": None,
        "totp_recovery_codes_hashes": [],
    }

    if payload.role == UserRole.DOCTOR:
        user_doc["registration_number"] = payload.registration_number
        user_doc["verification_status"] = DoctorVerificationStatus.PENDING.value
        user_doc["verified_by"] = None
        user_doc["verified_at"] = None

    result = await db["users"].insert_one(user_doc)
    user_id = str(result.inserted_id)
    user_doc["id"] = user_id

    # 4. Record audit entry
    await audit_service.insert(
        event_type=AuditEventType.USER_CREATION,
        actor_id=current_admin.id,
        actor_role=current_admin.role,
        target_user_id=user_id,
        details={
            "role": payload.role.value,
            "created_by": current_admin.email,
            "registration_number": payload.registration_number,
        },
        ip_address=ip_addr,
        user_agent=user_agent,
    )

    return UserResponse(**user_doc)


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    current_admin: Annotated[UserInDB, Depends(require_role(UserRole.ADMIN))],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    role: str | None = Query(None, description="Filter by role"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
) -> list[UserResponse]:
    """Lists users with optional role filtering and pagination. Admin only."""
    query = {}
    if role:
        query["role"] = role

    cursor = db["users"].find(query).sort("created_at", -1).skip(skip).limit(limit)
    users = []
    async for doc in cursor:
        doc["id"] = str(doc["_id"])
        users.append(UserResponse(**doc))
    return users


@router.post("/doctors/{doctor_id}/verify", response_model=UserResponse)
async def verify_doctor(
    doctor_id: str,
    payload: DoctorVerificationUpdate,
    request: Request,
    current_admin: Annotated[UserInDB, Depends(require_role(UserRole.ADMIN))],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> UserResponse:
    """
    Sets a doctor's clinical verification status to verified or rejected.
    Admin only. Records verified_by, verified_at, and writes to the audit log.
    """
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    try:
        query_id = ObjectId(doctor_id)
    except Exception:
        query_id = doctor_id

    user_doc = await db["users"].find_one({"_id": query_id})
    if not user_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Doctor not found")

    if user_doc.get("role") != UserRole.DOCTOR.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot verify non-doctor user.",
        )

    now = datetime.now(UTC)
    update_data = {
        "verification_status": payload.status.value,
        "verified_by": current_admin.id,
        "verified_at": now,
    }

    await db["users"].update_one({"_id": query_id}, {"$set": update_data})
    user_doc.update(update_data)
    user_doc["id"] = str(user_doc["_id"])

    await audit_service.insert(
        event_type=AuditEventType.VERIFICATION_CHANGES,
        actor_id=current_admin.id,
        actor_role=current_admin.role,
        target_user_id=doctor_id,
        details={
            "status": payload.status.value,
            "verified_by_email": current_admin.email,
        },
        ip_address=ip_addr,
        user_agent=user_agent,
    )

    return UserResponse(**user_doc)


@router.post("/users/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: str,
    request: Request,
    current_admin: Annotated[UserInDB, Depends(require_role(UserRole.ADMIN))],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> UserResponse:
    """
    Deactivates a user account immediately.
    Revokes any active refresh tokens and prevents further access.
    """
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    try:
        query_id = ObjectId(user_id)
    except Exception:
        query_id = user_id

    user_doc = await db["users"].find_one({"_id": query_id})
    if not user_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    now = datetime.now(UTC)
    await db["users"].update_one({"_id": query_id}, {"$set": {"is_active": False}})

    # Revoke all refresh tokens for this user
    await db["refresh_tokens"].update_many(
        {"user_id": str(user_doc["_id"])},
        {"$set": {"revoked": True, "revoked_at": now}},
    )

    user_doc["is_active"] = False
    user_doc["id"] = str(user_doc["_id"])

    await audit_service.insert(
        event_type=AuditEventType.DEACTIVATION,
        actor_id=current_admin.id,
        actor_role=current_admin.role,
        target_user_id=user_id,
        details={"is_active": False, "revoked_sessions": True},
        ip_address=ip_addr,
        user_agent=user_agent,
    )

    return UserResponse(**user_doc)
