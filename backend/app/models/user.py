from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.validators import AdultDateOfBirth, OncoLinkEmail


class UserRole(str, Enum):
    PATIENT = "patient"
    SCREENER = "screener"
    DOCTOR = "doctor"
    HOSPITAL_COORDINATOR = "hospital_coordinator"
    ADMIN = "admin"


class DoctorVerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class UserBase(BaseModel):
    email: OncoLinkEmail
    role: UserRole
    is_active: bool = True
    is_demo: bool = False


class PatientRegisterRequest(BaseModel):
    email: OncoLinkEmail
    password: str = Field(min_length=10)
    date_of_birth: AdultDateOfBirth
    consent_version: str
    consent_accepted: bool


class StaffUserCreate(BaseModel):
    email: OncoLinkEmail
    password: str = Field(min_length=10)
    role: UserRole
    registration_number: str | None = None


class DoctorVerificationUpdate(BaseModel):
    status: DoctorVerificationStatus


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: OncoLinkEmail
    role: UserRole
    is_active: bool = True
    is_demo: bool = False
    created_at: datetime
    registration_number: str | None = None
    verification_status: DoctorVerificationStatus | None = None
    verified_by: str | None = None
    verified_at: datetime | None = None
    totp_enrolled: bool = False
    patient_id: str | None = None


class UserInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: OncoLinkEmail
    password_hash: str
    role: UserRole
    is_active: bool = True
    is_demo: bool = False
    created_at: datetime

    # Doctor specific fields
    registration_number: str | None = None
    verification_status: DoctorVerificationStatus | None = None
    verified_by: str | None = None
    verified_at: datetime | None = None

    # Security & Lockout
    failed_login_attempts: int = 0
    locked_until: datetime | None = None

    # Two-Factor (TOTP)
    totp_enrolled: bool = False
    totp_secret_encrypted: str | None = None
    totp_recovery_codes_hashes: list[str] = Field(default_factory=list)
