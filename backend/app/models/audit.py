from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventType(str, Enum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOCKOUT = "lockout"
    LOGOUT = "logout"
    REFRESH_REUSE = "refresh_reuse"
    TOTP_ENROLLMENT = "totp_enrollment"
    USER_CREATION = "user_creation"
    VERIFICATION_CHANGES = "verification_changes"
    DEACTIVATION = "deactivation"


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    timestamp: datetime
    event_type: AuditEventType | str
    actor_id: str | None = None
    actor_role: str | None = None
    target_user_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
