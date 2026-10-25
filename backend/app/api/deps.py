from collections.abc import Callable
from typing import Annotated

from bson import ObjectId
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.database import get_database
from app.models.user import DoctorVerificationStatus, UserInDB, UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.case_service import CaseService
from app.services.consent_service import ConsentService
from app.services.image_service import ImageService
from app.services.patient_service import PatientService
from app.services.totp_service import TOTPService
from app.storage import GridFSStorageService, StorageService

security_bearer = HTTPBearer(auto_error=False)


# --- Service Dependencies ---


def get_current_settings(request: Request) -> Settings:
    """Returns app-specific settings (injected in create_app) or cached settings."""
    app_settings = getattr(request.app.state, "settings", None)
    return app_settings or get_settings()


def get_db(
    settings: Annotated[Settings, Depends(get_current_settings)],
) -> AsyncIOMotorDatabase:
    return get_database(settings.mongo_db_name)


def get_audit_service(db: Annotated[AsyncIOMotorDatabase, Depends(get_db)]) -> AuditService:
    return AuditService(db)


def get_auth_service(
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_current_settings)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> AuthService:
    return AuthService(db, settings, audit_service)


def get_totp_service(settings: Annotated[Settings, Depends(get_current_settings)]) -> TOTPService:
    return TOTPService(settings.totp_encryption_key)


def get_consent_service(db: Annotated[AsyncIOMotorDatabase, Depends(get_db)]) -> ConsentService:
    return ConsentService(db)


def get_patient_service(db: Annotated[AsyncIOMotorDatabase, Depends(get_db)]) -> PatientService:
    return PatientService(db)


def get_case_service(db: Annotated[AsyncIOMotorDatabase, Depends(get_db)]) -> CaseService:
    return CaseService(db)


def get_storage_service(db: Annotated[AsyncIOMotorDatabase, Depends(get_db)]) -> StorageService:
    return GridFSStorageService(db)


def get_image_service(
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    storage: Annotated[StorageService, Depends(get_storage_service)],
) -> ImageService:
    return ImageService(db, storage)


# --- User & Role Authentication Guards ---


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> UserInDB:
    """
    Validates the bearer access JWT and loads the user from the database on EVERY request.
    Rejects missing tokens, invalid tokens, and inactive users immediately.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = auth_service.decode_token(token, expected_type="access")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired credentials: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    user_id = payload.sub
    try:
        doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        doc = await db["users"].find_one({"_id": user_id})

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check is_active immediately: deactivation takes effect instantly
    if not doc.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Access denied.",
        )

    doc["id"] = str(doc["_id"])
    return UserInDB(**doc)


def require_role(*allowed_roles: UserRole | str) -> Callable[..., UserInDB]:
    """Reusable FastAPI role guard dependency."""
    allowed_str_roles = {str(r.value if isinstance(r, UserRole) else r) for r in allowed_roles}

    async def role_checker(
        current_user: Annotated[UserInDB, Depends(get_current_user)],
    ) -> UserInDB:
        if current_user.role not in allowed_str_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: role '{current_user.role}' lacks required permissions.",
            )
        return current_user

    return role_checker


async def require_verified_doctor(
    current_user: Annotated[UserInDB, Depends(get_current_user)],
) -> UserInDB:
    """
    Rejects doctors whose verification_status is not 'verified'.
    Also rejects any non-doctor roles attempting to access doctor-specific clinical signoff routes.
    """
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: endpoint restricted to verified medical doctors.",
        )

    if current_user.verification_status != DoctorVerificationStatus.VERIFIED:
        status_val = (
            current_user.verification_status.value
            if hasattr(current_user.verification_status, "value")
            else str(current_user.verification_status)
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Doctor verification status is '{status_val}'. "
                "Only verified doctors may access this endpoint."
            ),
        )

    return current_user


def get_client_ip(
    request: Request,
    x_forwarded_for: Annotated[str | None, Header()] = None,
) -> str | None:
    """Extracts client IP address respecting reverse proxies."""
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None
