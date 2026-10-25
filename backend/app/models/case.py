import re
import secrets
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# Unambiguous uppercase alphanumeric charset avoiding confusing chars (0/O, 1/I)
REFERENCE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
REFERENCE_REGEX = re.compile(r"^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}$")


def generate_case_reference() -> str:
    """
    Generates a cryptographically random, non-sequential case reference.
    Format: 8 characters grouped 4-4 (e.g. 'K9W2-P7M4').
    """
    part1 = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(4))
    part2 = "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(4))
    return f"{part1}-{part2}"


class CaseStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    QUALITY_CHECK = "quality_check"
    NEEDS_RETAKE = "needs_retake"
    QUEUED = "queued"
    AI_ANALYZED = "ai_analyzed"
    UNDER_REVIEW = "under_review"
    UNCERTAIN_NEEDS_INPERSON = "uncertain_needs_inperson"
    SIGNED = "signed"
    CLOSED_MONITOR = "closed_monitor"
    REFERRED = "referred"
    REFERRAL_PENDING = "referral_pending"
    CONFIRMED = "confirmed"
    ATTENDED = "attended"
    OUTCOME_RECORDED = "outcome_recorded"
    CLOSED = "closed"
    DECLINED_BY_HOSPITAL = "declined_by_hospital"
    NO_SHOW = "no_show"
    OUTREACH = "outreach"
    LOST_TO_FOLLOWUP = "lost_to_followup"
    CANCELLED = "cancelled"
    CONSENT_WITHDRAWN = "consent_withdrawn"
    RED_FLAG = "red_flag"


class Urgency(str, Enum):
    """
    Clinical review urgency tier determining review turnaround SLAs.
    Strictly decoupled from AI prediction certainty per docs/DECISIONS.md.
    """
    URGENT = "urgent"   # < 4 hours SLA
    SOON = "soon"       # < 24 hours SLA
    ROUTINE = "routine" # < 48 hours SLA


class ReasonCode(str, Enum):
    """Authoritative transition reason codes recorded in audit_log and status history."""
    # Draft & Creation
    DRAFT_CREATED = "draft_created"

    # Intake & Quality Check
    SELF_SCREEN_SUBMIT = "self_screen_submit"
    SCREENER_INTAKE_SUBMIT = "screener_intake_submit"
    PHOTO_QUALITY_PASSED = "photo_quality_passed"
    PHOTO_QUALITY_FAILED = "photo_quality_failed"
    PHOTO_RETAKE_SUBMITTED = "photo_retake_submitted"
    RED_FLAG_DETECTED = "red_flag_detected"
    AI_INFERENCE_COMPLETED = "ai_inference_completed"

    # Clinical Triage & Assignment
    DOCTOR_CLAIMED = "doctor_claimed"
    AUTO_ASSIGNED = "auto_assigned"
    DOCTOR_RELEASED = "doctor_released"
    DOCTOR_REQUESTED_RETAKE = "doctor_requested_retake"
    UNCERTAIN_LESION = "uncertain_lesion"
    SECOND_OPINION_REQUESTED = "second_opinion_requested"
    CLINICAL_SIGN_OFF = "clinical_sign_off"
    BENIGN_MONITOR = "benign_monitor"

    # Hospital Referrals & Appointments
    HOSPITAL_REFERRAL_ISSUED = "hospital_referral_issued"
    REFERRAL_TRANSMITTED = "referral_transmitted"
    HOSPITAL_ACCEPTED = "hospital_accepted"
    HOSPITAL_DECLINED = "hospital_declined"
    RE_REFERRAL_ISSUED = "re_referral_issued"
    PATIENT_ATTENDED = "patient_attended"
    PATIENT_NO_SHOW = "patient_no_show"
    OUTREACH_INITIATED = "outreach_initiated"
    OUTREACH_RESCHEDULED = "outreach_rescheduled"
    LOST_TO_FOLLOWUP = "lost_to_followup"
    BIOPSY_OUTCOME_RECORDED = "biopsy_outcome_recorded"
    CASE_CLOSED = "case_closed"

    # Cancellation & Privacy Erasure
    PATIENT_CANCELLED = "patient_cancelled"
    SCREENER_CANCELLED = "screener_cancelled"
    CONSENT_WITHDRAWN = "consent_withdrawn"

    # Administrative & Miscellaneous
    ADMIN_CORRECTION = "admin_correction"
    OTHER = "other"


class StatusHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: str
    to_status: str
    actor_id: str
    actor_role: str
    timestamp: datetime
    reason_code: str
    reason_text: str | None = None


class CaseInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    patient_id: str
    created_by: str
    status: CaseStatus = CaseStatus.DRAFT
    urgency: Urgency | None = None
    assigned_doctor_id: str | None = None
    second_opinion_doctor_id: str | None = None
    reference: str
    status_history: list[StatusHistoryEntry] = Field(default_factory=list)
    version: int = 1
    anatomical_sites: list[str] = Field(default_factory=list)
    is_demo: bool = False
    created_at: datetime
    updated_at: datetime


class CaseCreateRequest(BaseModel):
    patient_id: str | None = None  # Required for screeners; deduced from session for patients


class CaseStatusResponse(BaseModel):
    """Role-scoped case tracking response for patients and screeners (status only)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str
    status: CaseStatus
    patient_id: str
    created_at: datetime
    updated_at: datetime
    next_step: str | None = None


class CasePoolMetadataResponse(BaseModel):
    """
    Role-scoped metadata-only response for verified doctors viewing an unassigned pool case.
    Discloses zero photographic binaries and zero clinical questionnaire answers.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str
    status: CaseStatus
    age_band: str
    urgency: Urgency | None = None
    waiting_time_seconds: int
    anatomical_sites: list[str] = Field(default_factory=list)


class CaseDetailResponse(BaseModel):
    """Full clinical inspection response for assigned and second-opinion clinicians."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str
    patient_id: str
    created_by: str
    status: CaseStatus
    urgency: Urgency | None = None
    assigned_doctor_id: str | None = None
    second_opinion_doctor_id: str | None = None
    version: int
    anatomical_sites: list[str] = Field(default_factory=list)
    is_demo: bool = False
    created_at: datetime
    updated_at: datetime


class CaseTimelineResponse(BaseModel):
    """Chronological state transition timeline visible to assigned clinicians."""
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    reference: str
    timeline: list[StatusHistoryEntry]


class CaseCancelRequest(BaseModel):
    reason_text: str | None = None
