from datetime import UTC, datetime
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import (
    get_audit_service,
    get_auth_service,
    get_client_ip,
    get_consent_service,
    get_current_settings,
    get_current_user,
    get_db,
    get_totp_service,
)
from app.config import Settings
from app.models.audit import AuditEventType
from app.models.token import (
    LoginRequest,
    TokenResponse,
    TwoFactorSetupResponse,
    TwoFactorVerifyRequest,
    TwoFactorVerifySetupRequest,
    TwoFactorVerifySetupResponse,
)
from app.models.user import (
    PatientRegisterRequest,
    UserInDB,
    UserResponse,
    UserRole,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.consent_service import ConsentService
from app.services.totp_service import TOTPService

router = APIRouter(prefix="/auth", tags=["Authentication"])

REFRESH_COOKIE_NAME = "oncolink_refresh_token"


def _set_refresh_cookie(response: Response, raw_token: str, settings: Settings) -> None:
    """Sets secure httpOnly SameSite=Strict cookie for refresh token."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="strict",
        secure=(settings.environment == "production"),
        max_age=settings.refresh_token_expire_days * 86400,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clears refresh token cookie upon logout."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        httponly=True,
        samesite="strict",
        path="/",
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_patient(
    payload: PatientRegisterRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_current_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    consent_service: Annotated[ConsentService, Depends(get_consent_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> TokenResponse:
    """
    Patient self-registration.
    Requires acceptance of the current active informed consent version.
    Screeners, doctors, coordinators, and admins must be created by an administrator.
    """
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    # 1. Validate password strength
    try:
        auth_service.validate_password_strength(payload.password, payload.email)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    # 2. Verify informed consent acceptance
    if not payload.consent_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informed consent must be explicitly accepted to register as a participant.",
        )

    current_consent = consent_service.get_current_consent()
    if payload.consent_version != current_consent.version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Outdated consent version '{payload.consent_version}'. Active version is '{current_consent.version}'.",
        )

    # 3. Check for existing account
    normalized_email = payload.email.strip().lower()
    existing = await db["users"].find_one({"email": normalized_email})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    # 4. Create user record
    now = datetime.now(UTC)
    password_hash = auth_service.hash_password(payload.password)
    user_doc = {
        "email": normalized_email,
        "password_hash": password_hash,
        "role": UserRole.PATIENT.value,
        "is_active": True,
        "is_demo": False,
        "created_at": now,
        "failed_login_attempts": 0,
        "locked_until": None,
        "totp_enrolled": False,
        "totp_secret_encrypted": None,
        "totp_recovery_codes_hashes": [],
    }
    result = await db["users"].insert_one(user_doc)
    user_id = str(result.inserted_id)

    # 5. Record immutable consent record
    await consent_service.record_consent(
        user_id=user_id,
        version=payload.consent_version,
        captured_by="self",
    )

    # 6. Audit log
    await audit_service.insert(
        event_type=AuditEventType.USER_CREATION,
        actor_id=user_id,
        actor_role=UserRole.PATIENT.value,
        target_user_id=user_id,
        details={"role": UserRole.PATIENT.value, "registration_type": "patient_self_register"},
        ip_address=ip_addr,
        user_agent=user_agent,
    )

    # 7. Generate tokens and session
    access_token, expires_in = auth_service.create_access_token(user_id=user_id, role=UserRole.PATIENT.value)
    refresh_token = await auth_service.create_refresh_token(user_id=user_id)
    _set_refresh_cookie(response, refresh_token, settings)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user_id=user_id,
        role=UserRole.PATIENT.value,
        requires_2fa=False,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_current_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> TokenResponse:
    """
    Step 1 of authentication for all roles.
    - Locks account for 15 minutes after 5 failed attempts.
    - Returns generic error for unknown email and invalid password.
    - Doctors and admins require Step 2 TOTP verification.
    """
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    normalized_email = payload.email.strip().lower()
    user_doc = await db["users"].find_one({"email": normalized_email})

    generic_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not user_doc:
        # Unknown email: return generic error without revealing account existence
        raise generic_error

    # Check lockout
    is_locked = await auth_service.check_lockout(user_doc)
    if is_locked:
        await audit_service.insert(
            event_type=AuditEventType.LOGIN_FAILURE,
            actor_id=str(user_doc["_id"]),
            actor_role=user_doc.get("role"),
            target_user_id=str(user_doc["_id"]),
            details={"reason": "account_locked"},
            ip_address=ip_addr,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is temporarily locked due to multiple failed login attempts. Please try again later.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check active status
    if not user_doc.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Access denied.",
        )

    # Verify password
    valid = auth_service.verify_password(user_doc["password_hash"], payload.password)
    if not valid:
        locked_now = await auth_service.record_failed_attempt(user_doc, ip_address=ip_addr, user_agent=user_agent)
        if locked_now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is temporarily locked due to multiple failed login attempts. Please try again later.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise generic_error

    # Password is valid: reset failed attempts
    user_id = str(user_doc["_id"])
    role = user_doc["role"]
    await auth_service.reset_failed_attempts(user_doc["_id"])

    # Two-factor check for Doctor and Admin roles
    if role in (UserRole.DOCTOR.value, UserRole.ADMIN.value):
        temp_token = auth_service.create_temp_2fa_token(user_id=user_id, role=role)
        return TokenResponse(
            access_token="",
            token_type="bearer",
            expires_in=300,
            user_id=user_id,
            role=role,
            requires_2fa=True,
            temp_token=temp_token,
        )

    # Non-2FA roles (patient, screener, hospital_coordinator) receive tokens directly
    access_token, expires_in = auth_service.create_access_token(user_id=user_id, role=role)
    refresh_token = await auth_service.create_refresh_token(user_id=user_id)
    _set_refresh_cookie(response, refresh_token, settings)

    await audit_service.insert(
        event_type=AuditEventType.LOGIN_SUCCESS,
        actor_id=user_id,
        actor_role=role,
        target_user_id=user_id,
        details={"method": "password_only"},
        ip_address=ip_addr,
        user_agent=user_agent,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user_id=user_id,
        role=role,
        requires_2fa=False,
    )


@router.post("/2fa/login", response_model=TokenResponse)
async def login_2fa(
    payload: TwoFactorVerifyRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_current_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    totp_service: Annotated[TOTPService, Depends(get_totp_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> TokenResponse:
    """
    Step 2 of authentication for doctors and admins.
    Accepts the short-lived temp_token and either a 6-digit TOTP code or an 8-character recovery code.
    """
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    # 1. Decode temp token
    try:
        token_payload = auth_service.decode_token(payload.temp_token, expected_type="2fa_pending")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired 2FA session token: {e}",
        ) from e

    user_id = token_payload.sub
    try:
        user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        user_doc = await db["users"].find_one({"_id": user_id})

    if not user_doc or not user_doc.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account inactive or not found",
        )

    if not user_doc.get("totp_enrolled", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not enrolled. Please complete enrollment first.",
        )

    # 2. Verify code or recovery code
    authenticated = False
    used_recovery = False

    if payload.code:
        authenticated = totp_service.verify_code(
            user_doc.get("totp_secret_encrypted", ""),
            payload.code,
        )

    if not authenticated and payload.recovery_code:
        stored_hashes = user_doc.get("totp_recovery_codes_hashes", [])
        matched, remaining_hashes = totp_service.verify_and_consume_recovery_code(
            payload.recovery_code, stored_hashes
        )
        if matched:
            authenticated = True
            used_recovery = True
            await db["users"].update_one(
                {"_id": user_doc["_id"]},
                {"$set": {"totp_recovery_codes_hashes": remaining_hashes}},
            )

    if not authenticated:
        await audit_service.insert(
            event_type=AuditEventType.LOGIN_FAILURE,
            actor_id=user_id,
            actor_role=user_doc.get("role"),
            target_user_id=user_id,
            details={"reason": "invalid_2fa_code"},
            ip_address=ip_addr,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid two-factor authentication code or recovery code",
        )

    # 3. Issue session tokens
    role = user_doc["role"]
    access_token, expires_in = auth_service.create_access_token(user_id=user_id, role=role)
    refresh_token = await auth_service.create_refresh_token(user_id=user_id)
    _set_refresh_cookie(response, refresh_token, settings)

    await audit_service.insert(
        event_type=AuditEventType.LOGIN_SUCCESS,
        actor_id=user_id,
        actor_role=role,
        target_user_id=user_id,
        details={"method": "totp_recovery" if used_recovery else "totp_app"},
        ip_address=ip_addr,
        user_agent=user_agent,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
        user_id=user_id,
        role=role,
        requires_2fa=False,
    )


async def _get_user_for_enrollment(
    request: Request,
    db: AsyncIOMotorDatabase,
    auth_service: AuthService,
) -> UserInDB:
    """
    Extracts the user attempting TOTP enrollment.
    Accepts either an active Bearer token or a 2FA pending temp_token in header or query.
    """
    auth_header = request.headers.get("authorization", "")
    temp_header = request.headers.get("x-temp-token") or request.query_params.get("temp_token")

    user_id: str | None = None

    if temp_header:
        try:
            payload = auth_service.decode_token(temp_header, expected_type="2fa_pending")
            user_id = payload.sub
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid 2FA setup session: {e}",
            ) from e
    elif auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        try:
            # Could be access or 2fa_pending
            try:
                payload = auth_service.decode_token(token, expected_type="access")
            except ValueError:
                payload = auth_service.decode_token(token, expected_type="2fa_pending")
            user_id = payload.sub
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid credentials: {e}",
            ) from e
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for TOTP enrollment",
        )

    try:
        user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    except Exception:
        user_doc = await db["users"].find_one({"_id": user_id})

    if not user_doc or not user_doc.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account inactive or not found",
        )

    user_doc["id"] = str(user_doc["_id"])
    return UserInDB(**user_doc)


@router.post("/2fa/setup", response_model=TwoFactorSetupResponse)
async def setup_2fa(
    request: Request,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    totp_service: Annotated[TOTPService, Depends(get_totp_service)],
) -> TwoFactorSetupResponse:
    """
    Generates a new TOTP secret and provisioning URI for authenticator app enrollment.
    Available to unenrolled doctors and admins immediately after step 1 login.
    """
    user = await _get_user_for_enrollment(request, db, auth_service)
    secret = totp_service.generate_secret()
    uri = totp_service.get_provisioning_uri(secret, email=user.email)
    return TwoFactorSetupResponse(provisioning_uri=uri, secret=secret)


@router.post("/2fa/verify-setup", response_model=TwoFactorVerifySetupResponse)
async def verify_setup_2fa(
    payload: TwoFactorVerifySetupRequest,
    request: Request,
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    totp_service: Annotated[TOTPService, Depends(get_totp_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> TwoFactorVerifySetupResponse:
    """
    Confirms TOTP setup by verifying the user's first 6-digit code.
    Encrypts secret at rest and issues 8 single-use recovery codes stored as hashes.
    """
    user = await _get_user_for_enrollment(request, db, auth_service)
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    is_valid = totp_service.verify_raw_code(payload.secret, payload.code)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check your authenticator app and try again.",
        )

    # Encrypt secret for storage
    encrypted_secret = totp_service.encrypt_secret(payload.secret)
    plain_recovery, hashed_recovery = totp_service.generate_recovery_codes(8)

    try:
        query_id = ObjectId(user.id)
    except Exception:
        query_id = user.id

    await db["users"].update_one(
        {"_id": query_id},
        {
            "$set": {
                "totp_enrolled": True,
                "totp_secret_encrypted": encrypted_secret,
                "totp_recovery_codes_hashes": hashed_recovery,
            }
        },
    )

    await audit_service.insert(
        event_type=AuditEventType.TOTP_ENROLLMENT,
        actor_id=user.id,
        actor_role=user.role,
        target_user_id=user.id,
        details={"status": "enrolled", "recovery_codes_issued": len(plain_recovery)},
        ip_address=ip_addr,
        user_agent=user_agent,
    )

    return TwoFactorVerifySetupResponse(enrolled=True, recovery_codes=plain_recovery)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token_endpoint(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_current_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    oncolink_refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    """
    Rotates refresh token and returns a new 15-minute access JWT.
    Enforces reuse detection: presenting an already rotated token invalidates the entire token family.
    """
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    raw_token = oncolink_refresh_token
    if not raw_token:
        # Fallback to Authorization: Refresh <token> or X-Refresh-Token header if cookie unavailable
        raw_token = request.headers.get("x-refresh-token")

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )

    try:
        new_refresh_token, new_access_token, user = await auth_service.rotate_refresh_token(
            raw_token, ip_address=ip_addr, user_agent=user_agent
        )
    except ValueError as e:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        ) from e

    _set_refresh_cookie(response, new_refresh_token, settings)

    return TokenResponse(
        access_token=new_access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user_id=user.id,
        role=user.role,
        requires_2fa=False,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    oncolink_refresh_token: Annotated[str | None, Cookie()] = None,
) -> dict[str, str]:
    """
    Revokes the current refresh token and clears the session cookie.
    """
    ip_addr = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    raw_token = oncolink_refresh_token or request.headers.get("x-refresh-token")
    if raw_token:
        await auth_service.revoke_refresh_token(raw_token)

    _clear_refresh_cookie(response)

    # Attempt to log logout if user context is available
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            token = auth_header[7:].strip()
            payload = auth_service.decode_token(token, expected_type="access")
            await audit_service.insert(
                event_type=AuditEventType.LOGOUT,
                actor_id=payload.sub,
                actor_role=payload.role,
                target_user_id=payload.sub,
                details={"action": "logout"},
                ip_address=ip_addr,
                user_agent=user_agent,
            )
        except Exception:
            pass

    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[UserInDB, Depends(get_current_user)],
) -> UserResponse:
    """
    Returns the authenticated user's profile: id, email, role,
    verification status, and whether two-factor authentication is enrolled.
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        is_active=current_user.is_active,
        is_demo=current_user.is_demo,
        created_at=current_user.created_at,
        registration_number=current_user.registration_number,
        verification_status=current_user.verification_status,
        verified_by=current_user.verified_by,
        verified_at=current_user.verified_at,
        totp_enrolled=current_user.totp_enrolled,
    )
