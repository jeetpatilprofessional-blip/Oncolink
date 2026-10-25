import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config import Settings
from app.models.audit import AuditEventType
from app.models.token import TokenPayload
from app.models.user import UserInDB
from app.services.audit_service import AuditService

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15


class AuthService:
    """
    Core authentication, password hashing, session management,
    refresh token rotation, reuse detection, and lockout management.
    """

    def __init__(self, db: AsyncIOMotorDatabase, settings: Settings, audit_service: AuditService):
        self._db = db
        self._settings = settings
        self._audit = audit_service
        self._hasher = PasswordHasher()

    # --- Password Hashing & Validation ---

    def validate_password_strength(self, password: str, email: str) -> None:
        """Enforces minimum length of 10 characters and ensures password is not equal to email."""
        if len(password) < 10:
            raise ValueError("Password must be at least 10 characters long.")
        if password.strip().lower() == email.strip().lower():
            raise ValueError("Password must not equal email address.")

    def hash_password(self, password: str) -> str:
        """Hashes raw password using Argon2id."""
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        """Verifies raw password against stored Argon2 hash."""
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except Exception:
            return False

    # --- JWT Access Tokens ---

    def create_access_token(self, user_id: str, role: str) -> tuple[str, int]:
        """Creates a short-lived 15-minute access JWT."""
        now = datetime.now(UTC)
        expire_delta = timedelta(minutes=self._settings.access_token_expire_minutes)
        exp = now + expire_delta
        jti = str(uuid.uuid4())

        payload = {
            "sub": str(user_id),
            "role": str(role),
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "type": "access",
        }
        token = jwt.encode(payload, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm)
        expires_in = int(expire_delta.total_seconds())
        return token, expires_in

    def create_temp_2fa_token(self, user_id: str, role: str) -> str:
        """Creates a short-lived (5-minute) intermediate token for 2FA verification."""
        now = datetime.now(UTC)
        exp = now + timedelta(minutes=5)
        jti = str(uuid.uuid4())

        payload = {
            "sub": str(user_id),
            "role": str(role),
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "type": "2fa_pending",
        }
        return jwt.encode(payload, self._settings.jwt_secret, algorithm=self._settings.jwt_algorithm)

    def decode_token(self, token: str, expected_type: str = "access") -> TokenPayload:
        """Decodes and validates a JWT token signature, expiration, and type."""
        try:
            decoded = jwt.decode(
                token,
                self._settings.jwt_secret,
                algorithms=[self._settings.jwt_algorithm],
            )
            token_type = decoded.get("type")
            if token_type != expected_type:
                raise ValueError(f"Invalid token type: expected {expected_type}, got {token_type}")
            return TokenPayload(**decoded)
        except jwt.PyJWTError as e:
            raise ValueError(f"Invalid token: {e}") from e

    # --- Refresh Tokens & Reuse Detection ---

    @staticmethod
    def hash_refresh_token(token: str) -> str:
        """Computes SHA-256 hash of opaque refresh token for storage."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def create_refresh_token(self, user_id: str, family_id: str | None = None) -> str:
        """
        Generates an opaque refresh token, hashes it, and stores it in the database.
        Assigns or continues a token family for reuse detection.
        """
        raw_token = secrets.token_urlsafe(48)
        token_hash = self.hash_refresh_token(raw_token)
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=self._settings.refresh_token_expire_days)

        token_family = family_id or str(uuid.uuid4())

        doc = {
            "token_hash": token_hash,
            "family_id": token_family,
            "user_id": str(user_id),
            "expires_at": expires_at,
            "created_at": now,
            "revoked": False,
            "revoked_at": None,
        }
        await self._db["refresh_tokens"].insert_one(doc)
        return raw_token

    async def rotate_refresh_token(
        self,
        raw_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, str, UserInDB]:
        """
        Rotates an existing refresh token with reuse detection.
        If a revoked token is presented, REVOKES THE WHOLE TOKEN FAMILY and raises an exception.
        Returns: (new_raw_refresh_token, new_access_token, user).
        """
        token_hash = self.hash_refresh_token(raw_token)
        record = await self._db["refresh_tokens"].find_one({"token_hash": token_hash})

        if not record:
            raise ValueError("Invalid refresh token")

        family_id = record["family_id"]
        user_id = record["user_id"]

        now = datetime.now(UTC)

        # REUSE DETECTION: If this token was already revoked, someone is replaying a stolen token!
        if record.get("revoked", False):
            # Invalidate all tokens in this family immediately
            await self._db["refresh_tokens"].update_many(
                {"family_id": family_id},
                {"$set": {"revoked": True, "revoked_at": now}},
            )
            await self._audit.insert(
                event_type=AuditEventType.REFRESH_REUSE,
                actor_id=user_id,
                target_user_id=user_id,
                details={"family_id": family_id, "action": "family_revocation"},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise ValueError("Refresh token reuse detected. Session invalidated.")

        # Check expiration
        expires_at = record["expires_at"]
        if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now:
            raise ValueError("Refresh token expired")

        # Load user from database to ensure user is active
        from bson import ObjectId

        try:
            user_doc = await self._db["users"].find_one({"_id": ObjectId(user_id)})
        except Exception:
            user_doc = await self._db["users"].find_one({"_id": user_id})

        if not user_doc or not user_doc.get("is_active", True):
            raise ValueError("User account is inactive or not found")

        user_doc["id"] = str(user_doc["_id"])
        user = UserInDB(**user_doc)

        # Revoke the used refresh token
        await self._db["refresh_tokens"].update_one(
            {"token_hash": token_hash},
            {"$set": {"revoked": True, "revoked_at": now}},
        )

        # Issue new refresh token in the same family
        new_refresh_token = await self.create_refresh_token(user_id=user.id, family_id=family_id)

        # Issue new access token
        new_access_token, _ = self.create_access_token(user_id=user.id, role=user.role)

        return new_refresh_token, new_access_token, user

    async def revoke_refresh_token(self, raw_token: str) -> None:
        """Revokes a refresh token during explicit logout."""
        token_hash = self.hash_refresh_token(raw_token)
        now = datetime.now(UTC)
        await self._db["refresh_tokens"].update_one(
            {"token_hash": token_hash},
            {"$set": {"revoked": True, "revoked_at": now}},
        )

    # --- Lockout & Login Attempt Tracking ---

    async def check_lockout(self, user_doc: dict[str, Any]) -> bool:
        """Returns True if the user is currently locked out."""
        locked_until = user_doc.get("locked_until")
        if not locked_until:
            return False
        if isinstance(locked_until, datetime) and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        return locked_until > now

    async def record_failed_attempt(
        self,
        user_doc: dict[str, Any],
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> bool:
        """
        Increments failed login counter. If threshold is reached, locks account for 15 minutes.
        Returns True if the account is now locked.
        """
        now = datetime.now(UTC)
        user_id = user_doc["_id"]
        attempts = user_doc.get("failed_login_attempts", 0) + 1

        update: dict[str, Any] = {"failed_login_attempts": attempts}
        is_locked = False

        if attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            update["locked_until"] = locked_until
            is_locked = True

        await self._db["users"].update_one({"_id": user_id}, {"$set": update})

        if is_locked:
            await self._audit.insert(
                event_type=AuditEventType.LOCKOUT,
                actor_id=str(user_id),
                actor_role=user_doc.get("role"),
                target_user_id=str(user_id),
                details={"attempts": attempts, "duration_minutes": LOCKOUT_DURATION_MINUTES},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        else:
            await self._audit.insert(
                event_type=AuditEventType.LOGIN_FAILURE,
                actor_id=str(user_id),
                actor_role=user_doc.get("role"),
                target_user_id=str(user_id),
                details={"attempts": attempts, "reason": "invalid_credentials"},
                ip_address=ip_address,
                user_agent=user_agent,
            )

        return is_locked

    async def reset_failed_attempts(self, user_id: Any) -> None:
        """Resets failed login attempts on successful authentication."""
        await self._db["users"].update_one(
            {"_id": user_id},
            {"$set": {"failed_login_attempts": 0, "locked_until": None}},
        )
