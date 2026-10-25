import asyncio
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from bson import ObjectId
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.models.case import (
    CaseStatus,
    ReasonCode,
    generate_case_reference,
)
from app.models.user import DoctorVerificationStatus, UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.case_service import CaseService
from app.services.patient_service import PatientService
from app.services.state_machine import ALLOWED_TRANSITIONS, is_transition_allowed, transition

# Precomputed valid argon2 hash to avoid redundant crypto hashing during fast fixture setup
PRECOMPUTED_TEST_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$qN72ZkE9bZPvD3x0c+rUeQ$X5wWzJ9QvP7lM4jK8hF3tY6aB2cE1dG9uI0oR8sT4vU"
)


# ==============================================================================
# 1. Reference Generator Test
# ==============================================================================
def test_case_reference_format_uniqueness_and_non_sequential():
    """Generates 200 case references and proves they are unique, non-sequential, and formatted 4-4."""
    pattern = re.compile(r"^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{4}$")
    refs = [generate_case_reference() for _ in range(200)]

    # 1. Uniqueness
    assert len(set(refs)) == 200, "Collision detected in 200 case references"

    # 2. Format
    for r in refs:
        assert pattern.match(r), f"Reference '{r}' failed format validation"

    # 3. Non-sequential check: no adjacent items differ by a trivial counter suffix
    for i in range(len(refs) - 1):
        r1, r2 = refs[i], refs[i + 1]
        assert r1[:7] != r2[:7], f"Consecutive references '{r1}' and '{r2}' appear sequential"


# ==============================================================================
# 2. Under-18 Rejection Tests (Registration & Screener Patient Intake)
# ==============================================================================
@pytest.mark.asyncio
async def test_under_18_rejected_at_patient_registration(async_client: AsyncClient):
    """Patient self-registration must reject applicants under 18 years of age."""
    today = date.today()
    under_18_dob = (today - timedelta(days=17 * 365 + 3)).isoformat()

    res = await async_client.post(
        "/auth/register",
        json={
            "email": "minor_patient@example.com",
            "password": "ValidPassword123!",
            "date_of_birth": under_18_dob,
            "consent_version": "v1",
            "consent_accepted": True,
        },
    )
    assert res.status_code in (400, 422)
    assert "18" in res.text


@pytest.mark.asyncio
async def test_under_18_rejected_at_screener_patient_creation(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Screener intake profile creation must reject individuals under 18 years of age."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)

    now = datetime.now(UTC)
    user_doc = {
        "email": "screener_dob@example.com",
        "password_hash": PRECOMPUTED_TEST_HASH,
        "role": UserRole.SCREENER.value,
        "is_active": True,
        "is_demo": False,
        "created_at": now,
        "failed_login_attempts": 0,
        "locked_until": None,
        "totp_enrolled": True,
    }
    insert_res = await db["users"].insert_one(user_doc)
    screener_token, _ = auth_svc.create_access_token(user_id=str(insert_res.inserted_id), role=UserRole.SCREENER.value)
    headers = {"Authorization": f"Bearer {screener_token}"}

    today = date.today()
    under_18_dob = (today - timedelta(days=16 * 365 + 3)).isoformat()
    adult_dob = (today - timedelta(days=25 * 365)).isoformat()

    # Under 18 rejected
    minor_res = await async_client.post(
        "/patients",
        headers=headers,
        json={"date_of_birth": under_18_dob, "language": "en"},
    )
    assert minor_res.status_code in (400, 422)
    assert "18" in minor_res.text

    # Adult (age >= 18) accepted
    adult_res = await async_client.post(
        "/patients",
        headers=headers,
        json={"date_of_birth": adult_dob, "language": "en"},
    )
    assert adult_res.status_code == 201
    assert adult_res.json()["date_of_birth"] == adult_dob


# ==============================================================================
# 3. Admin Role Zero Allowed Edges Invariant Test
# ==============================================================================
def test_admin_role_has_zero_allowed_edges():
    """Asserts that the admin role has zero allowed state transitions in ALLOWED_TRANSITIONS."""
    for (from_st, to_st), allowed_roles in ALLOWED_TRANSITIONS.items():
        assert UserRole.ADMIN.value not in allowed_roles, (
            f"Admin role unexpectedly allowed in transition {from_st} -> {to_st}"
        )
        assert "admin" not in allowed_roles, (
            f"String 'admin' unexpectedly allowed in transition {from_st} -> {to_st}"
        )


# ==============================================================================
# 4. Pure Function State Machine Cross-Product Test (3,174 Checks, No DB)
# ==============================================================================
def test_state_machine_pure_cross_product_transitions():
    """
    Exhaustively evaluates all 23x23=529 state pairs across all 6 roles (3,174 evaluations)
    against the pure is_transition_allowed function in memory without any database I/O.
    """
    all_states = list(CaseStatus)
    roles = [
        UserRole.PATIENT.value,
        UserRole.SCREENER.value,
        UserRole.DOCTOR.value,
        UserRole.HOSPITAL_COORDINATOR.value,
        UserRole.ADMIN.value,
        "system",
    ]

    total_evaluations = 0
    allowed_count = 0

    for from_st in all_states:
        for to_st in all_states:
            for role in roles:
                total_evaluations += 1
                allowed = is_transition_allowed(from_st, to_st, role)
                allowed_roles = ALLOWED_TRANSITIONS.get((from_st, to_st), set())

                # Special conditional edge: outreach -> confirmed requires new appointment condition
                if (from_st, to_st) == (CaseStatus.OUTREACH, CaseStatus.CONFIRMED):
                    assert not is_transition_allowed(from_st, to_st, role)
                    if role == UserRole.HOSPITAL_COORDINATOR.value:
                        assert is_transition_allowed(from_st, to_st, role, {"new_appointment_exists": True})
                    continue

                expected = role in allowed_roles
                if allowed:
                    allowed_count += 1
                    assert expected, f"Unexpectedly allowed transition: {from_st} -> {to_st} for role {role}"
                else:
                    assert not expected, f"Denied valid edge: {from_st} -> {to_st} for role {role}"

    assert total_evaluations == len(all_states) * len(all_states) * len(roles)
    assert allowed_count > 0


# ==============================================================================
# 5. Database-Backed Allowed Transitions Test (Every Allowed Edge)
# ==============================================================================
ALLOWED_EDGE_CASES = [
    (CaseStatus.DRAFT, CaseStatus.SUBMITTED, UserRole.PATIENT.value, ReasonCode.SELF_SCREEN_SUBMIT.value, None),
    (CaseStatus.SUBMITTED, CaseStatus.QUALITY_CHECK, "system", ReasonCode.PHOTO_QUALITY_PASSED.value, None),
    (CaseStatus.SUBMITTED, CaseStatus.RED_FLAG, "system", ReasonCode.RED_FLAG_DETECTED.value, None),
    (CaseStatus.QUALITY_CHECK, CaseStatus.NEEDS_RETAKE, "system", ReasonCode.PHOTO_QUALITY_FAILED.value, None),
    (CaseStatus.QUALITY_CHECK, CaseStatus.QUEUED, "system", ReasonCode.PHOTO_QUALITY_PASSED.value, None),
    (CaseStatus.NEEDS_RETAKE, CaseStatus.SUBMITTED, UserRole.SCREENER.value, ReasonCode.PHOTO_RETAKE_SUBMITTED.value, None),
    (CaseStatus.QUEUED, CaseStatus.AI_ANALYZED, "system", ReasonCode.AI_INFERENCE_COMPLETED.value, None),
    (CaseStatus.AI_ANALYZED, CaseStatus.UNDER_REVIEW, UserRole.DOCTOR.value, ReasonCode.DOCTOR_CLAIMED.value, None),
    (CaseStatus.UNDER_REVIEW, CaseStatus.AI_ANALYZED, UserRole.DOCTOR.value, ReasonCode.DOCTOR_RELEASED.value, None),
    (CaseStatus.UNDER_REVIEW, CaseStatus.NEEDS_RETAKE, UserRole.DOCTOR.value, ReasonCode.DOCTOR_REQUESTED_RETAKE.value, None),
    (CaseStatus.UNDER_REVIEW, CaseStatus.UNCERTAIN_NEEDS_INPERSON, UserRole.DOCTOR.value, ReasonCode.UNCERTAIN_LESION.value, None),
    (CaseStatus.UNDER_REVIEW, CaseStatus.SIGNED, UserRole.DOCTOR.value, ReasonCode.CLINICAL_SIGN_OFF.value, None),
    (CaseStatus.SIGNED, CaseStatus.CLOSED_MONITOR, UserRole.DOCTOR.value, ReasonCode.BENIGN_MONITOR.value, None),
    (CaseStatus.SIGNED, CaseStatus.REFERRED, UserRole.DOCTOR.value, ReasonCode.HOSPITAL_REFERRAL_ISSUED.value, None),
    (CaseStatus.REFERRED, CaseStatus.REFERRAL_PENDING, "system", ReasonCode.REFERRAL_TRANSMITTED.value, None),
    (CaseStatus.REFERRAL_PENDING, CaseStatus.CONFIRMED, UserRole.HOSPITAL_COORDINATOR.value, ReasonCode.HOSPITAL_ACCEPTED.value, None),
    (CaseStatus.REFERRAL_PENDING, CaseStatus.DECLINED_BY_HOSPITAL, UserRole.HOSPITAL_COORDINATOR.value, ReasonCode.HOSPITAL_DECLINED.value, None),
    (CaseStatus.DECLINED_BY_HOSPITAL, CaseStatus.REFERRED, UserRole.DOCTOR.value, ReasonCode.RE_REFERRAL_ISSUED.value, None),
    (CaseStatus.CONFIRMED, CaseStatus.ATTENDED, UserRole.HOSPITAL_COORDINATOR.value, ReasonCode.PATIENT_ATTENDED.value, None),
    (CaseStatus.CONFIRMED, CaseStatus.NO_SHOW, UserRole.HOSPITAL_COORDINATOR.value, ReasonCode.PATIENT_NO_SHOW.value, None),
    (CaseStatus.NO_SHOW, CaseStatus.OUTREACH, UserRole.SCREENER.value, ReasonCode.OUTREACH_INITIATED.value, None),
    (
        CaseStatus.OUTREACH,
        CaseStatus.CONFIRMED,
        UserRole.HOSPITAL_COORDINATOR.value,
        ReasonCode.OUTREACH_RESCHEDULED.value,
        {"new_appointment_exists": True},
    ),
    (CaseStatus.OUTREACH, CaseStatus.LOST_TO_FOLLOWUP, UserRole.HOSPITAL_COORDINATOR.value, ReasonCode.LOST_TO_FOLLOWUP.value, None),
    (CaseStatus.ATTENDED, CaseStatus.OUTCOME_RECORDED, UserRole.HOSPITAL_COORDINATOR.value, ReasonCode.BIOPSY_OUTCOME_RECORDED.value, None),
    (CaseStatus.OUTCOME_RECORDED, CaseStatus.CLOSED, UserRole.HOSPITAL_COORDINATOR.value, ReasonCode.CASE_CLOSED.value, None),
    # Pre-signing cancellations
    (CaseStatus.DRAFT, CaseStatus.CANCELLED, UserRole.PATIENT.value, ReasonCode.PATIENT_CANCELLED.value, None),
    (CaseStatus.SUBMITTED, CaseStatus.CANCELLED, UserRole.PATIENT.value, ReasonCode.PATIENT_CANCELLED.value, None),
    (CaseStatus.QUALITY_CHECK, CaseStatus.CANCELLED, UserRole.PATIENT.value, ReasonCode.PATIENT_CANCELLED.value, None),
    (CaseStatus.NEEDS_RETAKE, CaseStatus.CANCELLED, UserRole.PATIENT.value, ReasonCode.PATIENT_CANCELLED.value, None),
    (CaseStatus.QUEUED, CaseStatus.CANCELLED, UserRole.PATIENT.value, ReasonCode.PATIENT_CANCELLED.value, None),
    (CaseStatus.AI_ANALYZED, CaseStatus.CANCELLED, UserRole.PATIENT.value, ReasonCode.PATIENT_CANCELLED.value, None),
    (CaseStatus.UNDER_REVIEW, CaseStatus.CANCELLED, UserRole.PATIENT.value, ReasonCode.PATIENT_CANCELLED.value, None),
    (CaseStatus.UNCERTAIN_NEEDS_INPERSON, CaseStatus.CANCELLED, UserRole.PATIENT.value, ReasonCode.PATIENT_CANCELLED.value, None),
    # Consent withdrawn edges
    (CaseStatus.UNDER_REVIEW, CaseStatus.CONSENT_WITHDRAWN, UserRole.PATIENT.value, ReasonCode.CONSENT_WITHDRAWN.value, None),
    (CaseStatus.SIGNED, CaseStatus.CONSENT_WITHDRAWN, UserRole.PATIENT.value, ReasonCode.CONSENT_WITHDRAWN.value, None),
]


@pytest.mark.parametrize(
    "from_st, to_st, role, reason_code, extra",
    ALLOWED_EDGE_CASES,
    ids=[f"{c[0].value}->{c[1].value}({c[2]})" for c in ALLOWED_EDGE_CASES],
)
@pytest.mark.asyncio
async def test_state_machine_allowed_edge_db(
    from_st: CaseStatus,
    to_st: CaseStatus,
    role: str,
    reason_code: str,
    extra: dict[str, Any] | None,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Proves that every allowed edge executes cleanly in the real database transaction."""
    db = test_mongo_client[test_settings.mongo_db_name]
    case_svc = CaseService(db)

    # Create initial case
    case = await case_svc.create_case_draft(patient_id="patient_123", created_by="user_123")
    actor_id = "doc_123" if role == UserRole.DOCTOR.value else "user_123"
    assigned_doc_id = (
        "doc_123"
        if (from_st in (CaseStatus.UNDER_REVIEW, CaseStatus.SIGNED, CaseStatus.DECLINED_BY_HOSPITAL) and role == UserRole.DOCTOR.value)
        else None
    )

    # Set to initial from_st
    await db["cases"].update_one(
        {"_id": ObjectId(case.id)},
        {"$set": {"status": from_st.value, "assigned_doctor_id": assigned_doc_id}},
    )

    actor = {
        "id": actor_id,
        "patient_id": "patient_123",
        "role": role,
        "is_verified": True,
    }
    res = await transition(
        case_id=case.id,
        to_state=to_st,
        actor=actor,
        reason_code=reason_code,
        extra_conditions=extra,
        db=db,
    )
    assert res["status"] == to_st.value

    # Verify persisted in database
    persisted = await db["cases"].find_one({"_id": ObjectId(case.id)})
    assert persisted["status"] == to_st.value
    assert persisted["version"] == 2
    assert persisted["status_history"][-1]["to_status"] == to_st.value
    if from_st == CaseStatus.UNDER_REVIEW and to_st == CaseStatus.AI_ANALYZED:
        # Voluntary release unassigns doctor
        assert persisted.get("assigned_doctor_id") is None


# ==============================================================================
# 6. State-Dependent 409 for POST /cases/{id}/cancel
# ==============================================================================
@pytest.mark.asyncio
async def test_case_cancellation_pre_vs_post_signing_states(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    POST /cases/{id}/cancel is permitted in states prior to 'signed' and returns
    409 Conflict in signed or any subsequent state.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    now = datetime.now(UTC)
    patient_user_doc = {
        "email": "cancel_patient@example.com",
        "password_hash": PRECOMPUTED_TEST_HASH,
        "role": UserRole.PATIENT.value,
        "is_active": True,
        "is_demo": False,
        "created_at": now,
        "failed_login_attempts": 0,
        "locked_until": None,
        "totp_enrolled": True,
    }
    res_u = await db["users"].insert_one(patient_user_doc)
    patient_id = str(res_u.inserted_id)
    token, _ = auth_svc.create_access_token(user_id=patient_id, role=UserRole.PATIENT.value)

    p_profile = await patient_svc.create_patient(
        created_by=patient_id,
        date_of_birth="1990-01-01",
        user_id=patient_id,
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Pre-signing cancellation succeeds
    pre_case = await case_svc.create_case_draft(patient_id=p_profile.id, created_by=patient_id)
    cancel_res_1 = await async_client.post(f"/cases/{pre_case.id}/cancel", headers=headers)
    assert cancel_res_1.status_code == 200
    assert cancel_res_1.json()["status"] == CaseStatus.CANCELLED.value

    # 2. Post-signing states return 409 Conflict
    post_signing_states = [
        CaseStatus.SIGNED,
        CaseStatus.REFERRED,
        CaseStatus.REFERRAL_PENDING,
        CaseStatus.CONFIRMED,
        CaseStatus.ATTENDED,
        CaseStatus.OUTCOME_RECORDED,
        CaseStatus.CLOSED,
        CaseStatus.CANCELLED,
    ]

    for st in post_signing_states:
        case_doc = await case_svc.create_case_draft(patient_id=p_profile.id, created_by=patient_id)
        await db["cases"].update_one({"_id": ObjectId(case_doc.id)}, {"$set": {"status": st.value}})

        conflict_res = await async_client.post(f"/cases/{case_doc.id}/cancel", headers=headers)
        assert conflict_res.status_code == 409, f"Expected 409 for status '{st.value}', got {conflict_res.status_code}"


# ==============================================================================
# 7. Rollback Test: Transactional Atomicity on Audit Failure
# ==============================================================================
@pytest.mark.asyncio
async def test_state_machine_rollback_on_audit_write_failure(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    If the audit log write fails inside state machine transition(), the entire
    MongoDB transaction must roll back, leaving case status, version, and history unchanged.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    p_profile = await patient_svc.create_patient(
        created_by="user_patient_rollback",
        date_of_birth="1990-01-01",
        user_id="user_patient_rollback",
    )

    case = await case_svc.create_case_draft(patient_id=p_profile.id, created_by="user_patient_rollback")
    initial_version = case.version

    with patch.object(AuditService, "insert", side_effect=RuntimeError("Forced audit failure")):
        with pytest.raises(RuntimeError, match="Forced audit failure"):
            actor = {"id": "user_patient_rollback", "role": UserRole.PATIENT.value, "patient_id": p_profile.id}
            await transition(
                case_id=case.id,
                to_state=CaseStatus.SUBMITTED,
                actor=actor,
                reason_code=ReasonCode.SELF_SCREEN_SUBMIT,
                db=db,
            )

    # Verify document in DB is untouched
    persisted = await db["cases"].find_one({"_id": ObjectId(case.id)})
    assert persisted["status"] == CaseStatus.DRAFT.value
    assert persisted["version"] == initial_version
    assert len(persisted["status_history"]) == 1


# ==============================================================================
# 8. Concurrency Test: Two Simultaneous Transitions Yield One Winner and One 409
# ==============================================================================
@pytest.mark.asyncio
async def test_concurrent_transitions_yield_one_winner_and_one_conflict(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Two concurrent transitions on the same case from the same version must yield
    exactly one success and one 409 Conflict.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    p_profile = await patient_svc.create_patient(
        created_by="user_concurrency",
        date_of_birth="1990-01-01",
        user_id="user_concurrency",
    )
    case = await case_svc.create_case_draft(patient_id=p_profile.id, created_by="user_concurrency")
    actor = {"id": "user_concurrency", "role": UserRole.PATIENT.value, "patient_id": p_profile.id}

    async def do_transition(target_st, reason):
        try:
            return await transition(
                case_id=case.id,
                to_state=target_st,
                actor=actor,
                reason_code=reason,
                db=db,
            )
        except Exception as e:
            return e

    # Launch two simultaneous transitions
    results = await asyncio.gather(
        do_transition(CaseStatus.SUBMITTED, ReasonCode.SELF_SCREEN_SUBMIT),
        do_transition(CaseStatus.CANCELLED, ReasonCode.PATIENT_CANCELLED),
    )

    successes = [r for r in results if isinstance(r, dict)]
    failures = [r for r in results if not isinstance(r, dict)]

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(failures) == 1, f"Expected exactly 1 failure, got {len(failures)}"
    assert failures[0].status_code == 409, f"Expected 409 Conflict, got {failures[0]}"

    case_in_db = await db["cases"].find_one({"_id": ObjectId(case.id)})
    assert case_in_db["version"] == 2


# ==============================================================================
# 9. Reason Text Privacy Invariant Test
# ==============================================================================
@pytest.mark.asyncio
async def test_reason_text_never_written_to_audit_log(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Proves that reason_text is stored strictly in status_history and is NEVER
    persisted into the audit_log collection.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    p_profile = await patient_svc.create_patient(
        created_by="user_privacy",
        date_of_birth="1990-01-01",
        user_id="user_privacy",
    )
    case = await case_svc.create_case_draft(patient_id=p_profile.id, created_by="user_privacy")
    secret_text = "SECRET_PATIENT_REASON_TEXT_SENSITIVE_NOTE_12345"

    actor = {"id": "user_privacy", "role": UserRole.PATIENT.value, "patient_id": p_profile.id}
    await transition(
        case_id=case.id,
        to_state=CaseStatus.SUBMITTED,
        actor=actor,
        reason_code=ReasonCode.SELF_SCREEN_SUBMIT,
        reason_text=secret_text,
        db=db,
    )

    # 1. Proves secret_text is in status_history
    persisted_case = await db["cases"].find_one({"_id": ObjectId(case.id)})
    assert persisted_case["status_history"][-1]["reason_text"] == secret_text

    # 2. Proves secret_text is NEVER in audit_log
    audit_records = await db["audit_log"].find({}).to_list(100)
    for record in audit_records:
        rec_str = str(record)
        assert secret_text not in rec_str, f"Privacy violation: audit log record contains reason_text: {rec_str}"


# ==============================================================================
# 10. Source Scan Invariant Test
# ==============================================================================
def test_no_source_file_outside_state_machine_writes_case_status():
    """
    Invariant: Nothing else in the codebase may write a case status.
    Scans all .py files in app/ (except state_machine.py) and ensures none update case status.
    """
    app_dir = Path(__file__).parent.parent / "app"
    forbidden_patterns = [
        re.compile(r'\$set["\']\s*:\s*\{[^}]*["\']status["\']'),
        re.compile(r'update_one\([^)]*["\']status["\']'),
        re.compile(r'update_many\([^)]*["\']status["\']'),
        re.compile(r'find_one_and_update\([^)]*["\']status["\']'),
    ]

    for py_file in app_dir.rglob("*.py"):
        if py_file.name == "state_machine.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        for pat in forbidden_patterns:
            match = pat.search(content)
            assert not match, f"Forbidden case status write detected in {py_file}: {match.group(0)}"


# ==============================================================================
# 11. Granular Parametrized Authorization Matrix Tests Across All Built Endpoints
# ==============================================================================

MATRIX_SPECS = [
    # 1. POST /patients (screener creates profile)
    (
        "POST_/patients",
        "POST",
        "/patients",
        {"date_of_birth": "1990-01-01", "language": "en"},
        {
            "Unauth": 401,
            "Patient_(Owner)": 403,
            "Patient_(Other)": 403,
            "Screener_(Creator)": 201,
            "Screener_(Other)": 201,
            "Doctor_(Assigned)": 403,
            "Doctor_(Second_opinion)": 403,
            "Doctor_(verified,_pool_case)": 403,
            "Doctor_(Other)": 403,
            "Doctor_(Unverified)": 403,
            "Coord_(Own_Hosp)": 403,
            "Coord_(Other_Hosp)": 403,
            "Admin": 403,
        },
    ),
    # 2. POST /cases (draft creation)
    (
        "POST_/cases",
        "POST",
        "/cases",
        "DYNAMIC_CASE_PAYLOAD",
        {
            "Unauth": 401,
            "Patient_(Owner)": 201,
            "Patient_(Other)": 201,
            "Screener_(Creator)": 201,
            "Screener_(Other)": 404,
            "Doctor_(Assigned)": 403,
            "Doctor_(Second_opinion)": 403,
            "Doctor_(verified,_pool_case)": 403,
            "Doctor_(Other)": 403,
            "Doctor_(Unverified)": 403,
            "Coord_(Own_Hosp)": 403,
            "Coord_(Other_Hosp)": 403,
            "Admin": 403,
        },
    ),
    # 3. GET /cases (list cases)
    (
        "GET_/cases",
        "GET",
        "/cases",
        None,
        {
            "Unauth": 401,
            "Patient_(Owner)": 200,
            "Patient_(Other)": 200,
            "Screener_(Creator)": 200,
            "Screener_(Other)": 200,
            "Doctor_(Assigned)": 403,
            "Doctor_(Second_opinion)": 403,
            "Doctor_(verified,_pool_case)": 403,
            "Doctor_(Other)": 403,
            "Doctor_(Unverified)": 403,
            "Coord_(Own_Hosp)": 403,
            "Coord_(Other_Hosp)": 403,
            "Admin": 403,
        },
    ),
    # 4. GET /cases/{id} on Assigned Case A
    (
        "GET_/cases/{id}_Assigned",
        "GET",
        "TARGET_CASE_A",
        None,
        {
            "Unauth": 401,
            "Patient_(Owner)": 200,
            "Patient_(Other)": 404,
            "Screener_(Creator)": 200,
            "Screener_(Other)": 404,
            "Doctor_(Assigned)": 200,
            "Doctor_(Second_opinion)": 200,
            "Doctor_(verified,_pool_case)": 404,
            "Doctor_(Other)": 404,
            "Doctor_(Unverified)": 403,
            "Coord_(Own_Hosp)": 403,
            "Coord_(Other_Hosp)": 403,
            "Admin": 403,
        },
    ),
    # 5. GET /cases/{id} on Pool Case B (ai_analyzed, unassigned)
    (
        "GET_/cases/{id}_Pool",
        "GET",
        "TARGET_CASE_B_POOL",
        None,
        {
            "Unauth": 401,
            "Doctor_(verified,_pool_case)": 200,
            "Doctor_(Unverified)": 403,
        },
    ),
    # 6. GET /cases/{id}/timeline (Assigned Case A)
    (
        "GET_/cases/{id}/timeline",
        "GET",
        "TARGET_CASE_A_TIMELINE",
        None,
        {
            "Unauth": 401,
            "Patient_(Owner)": 403,
            "Patient_(Other)": 403,
            "Screener_(Creator)": 403,
            "Screener_(Other)": 403,
            "Doctor_(Assigned)": 200,
            "Doctor_(Second_opinion)": 200,
            "Doctor_(verified,_pool_case)": 404,
            "Doctor_(Other)": 404,
            "Doctor_(Unverified)": 403,
            "Coord_(Own_Hosp)": 403,
            "Coord_(Other_Hosp)": 403,
            "Admin": 403,
        },
    ),
    # 7. POST /consent
    (
        "POST_/consent",
        "POST",
        "/consent",
        "DYNAMIC_CONSENT_PAYLOAD",
        {
            "Unauth": 401,
            "Patient_(Owner)": 201,
            "Patient_(Other)": 404,
            "Screener_(Creator)": 404,
            "Screener_(Other)": 404,
            "Doctor_(Assigned)": 403,
            "Doctor_(Second_opinion)": 403,
            "Doctor_(verified,_pool_case)": 403,
            "Doctor_(Other)": 403,
            "Doctor_(Unverified)": 403,
            "Coord_(Own_Hosp)": 403,
            "Coord_(Other_Hosp)": 403,
            "Admin": 403,
        },
    ),
    # 8. POST /auth/register
    (
        "POST_/auth/register",
        "POST",
        "/auth/register",
        {
            "email": "granular_reg_patient@example.com",
            "password": "ValidPassword123!",
            "date_of_birth": "1991-01-01",
            "consent_version": "v1",
            "consent_accepted": True,
        },
        {
            "Unauth": 201,
            "Patient_(Owner)": 403,
            "Patient_(Other)": 403,
            "Screener_(Creator)": 403,
            "Screener_(Other)": 403,
            "Doctor_(Assigned)": 403,
            "Doctor_(Second_opinion)": 403,
            "Doctor_(verified,_pool_case)": 403,
            "Doctor_(Other)": 403,
            "Doctor_(Unverified)": 403,
            "Coord_(Own_Hosp)": 403,
            "Coord_(Other_Hosp)": 403,
            "Admin": 403,
        },
    ),
]

MATRIX_CELLS = []
MATRIX_CELL_IDS = []
for name, method, target_spec, payload_spec, persona_map in MATRIX_SPECS:
    for persona, exp_status in persona_map.items():
        test_id = f"{name}--{persona}--{exp_status}"
        MATRIX_CELLS.append((name, method, target_spec, payload_spec, persona, exp_status))
        MATRIX_CELL_IDS.append(test_id)


@pytest.mark.parametrize(
    "name, method, target_spec, payload_spec, persona, expected_status",
    MATRIX_CELLS,
    ids=MATRIX_CELL_IDS,
)
@pytest.mark.asyncio
async def test_authorization_matrix_cell(
    name: str,
    method: str,
    target_spec: Any,
    payload_spec: Any,
    persona: str,
    expected_status: int,
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Granular parametrized authorization test verifying an individual (endpoint, persona) cell.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    now = datetime.now(UTC)

    # 1. Fast Batch Provisioning of Test Personas
    user_docs = [
        {"_id": ObjectId("660000000000000000000001"), "email": "p_owner@test.local", "role": UserRole.PATIENT.value},
        {"_id": ObjectId("660000000000000000000002"), "email": "p_other@test.local", "role": UserRole.PATIENT.value},
        {"_id": ObjectId("660000000000000000000003"), "email": "scr_creator@test.local", "role": UserRole.SCREENER.value},
        {"_id": ObjectId("660000000000000000000004"), "email": "scr_other@test.local", "role": UserRole.SCREENER.value},
        {
            "_id": ObjectId("660000000000000000000005"),
            "email": "doc_assigned@test.local",
            "role": UserRole.DOCTOR.value,
            "verification_status": DoctorVerificationStatus.VERIFIED.value,
        },
        {
            "_id": ObjectId("660000000000000000000006"),
            "email": "doc_second_op@test.local",
            "role": UserRole.DOCTOR.value,
            "verification_status": DoctorVerificationStatus.VERIFIED.value,
        },
        {
            "_id": ObjectId("660000000000000000000007"),
            "email": "doc_pool@test.local",
            "role": UserRole.DOCTOR.value,
            "verification_status": DoctorVerificationStatus.VERIFIED.value,
        },
        {
            "_id": ObjectId("660000000000000000000008"),
            "email": "doc_other@test.local",
            "role": UserRole.DOCTOR.value,
            "verification_status": DoctorVerificationStatus.VERIFIED.value,
        },
        {
            "_id": ObjectId("660000000000000000000009"),
            "email": "doc_unverified@test.local",
            "role": UserRole.DOCTOR.value,
            "verification_status": DoctorVerificationStatus.PENDING.value,
        },
        {
            "_id": ObjectId("66000000000000000000000a"),
            "email": "coord_own@test.local",
            "role": UserRole.HOSPITAL_COORDINATOR.value,
            "hospital_id": "HOSP_01",
        },
        {
            "_id": ObjectId("66000000000000000000000b"),
            "email": "coord_other@test.local",
            "role": UserRole.HOSPITAL_COORDINATOR.value,
            "hospital_id": "HOSP_02",
        },
        {"_id": ObjectId("66000000000000000000000c"), "email": "admin@test.local", "role": UserRole.ADMIN.value},
    ]

    for u in user_docs:
        u.setdefault("password_hash", PRECOMPUTED_TEST_HASH)
        u.setdefault("is_active", True)
        u.setdefault("is_demo", False)
        u.setdefault("created_at", now)
        u.setdefault("failed_login_attempts", 0)
        u.setdefault("locked_until", None)
        u.setdefault("totp_enrolled", True)

    await db["users"].insert_many(user_docs)

    # 2. Fast Token Generation
    tokens = {
        "Unauth": None,
        "Patient_(Owner)": auth_svc.create_access_token(user_id="660000000000000000000001", role=UserRole.PATIENT.value)[0],
        "Patient_(Other)": auth_svc.create_access_token(user_id="660000000000000000000002", role=UserRole.PATIENT.value)[0],
        "Screener_(Creator)": auth_svc.create_access_token(user_id="660000000000000000000003", role=UserRole.SCREENER.value)[0],
        "Screener_(Other)": auth_svc.create_access_token(user_id="660000000000000000000004", role=UserRole.SCREENER.value)[0],
        "Doctor_(Assigned)": auth_svc.create_access_token(user_id="660000000000000000000005", role=UserRole.DOCTOR.value)[0],
        "Doctor_(Second_opinion)": auth_svc.create_access_token(user_id="660000000000000000000006", role=UserRole.DOCTOR.value)[0],
        "Doctor_(verified,_pool_case)": auth_svc.create_access_token(user_id="660000000000000000000007", role=UserRole.DOCTOR.value)[0],
        "Doctor_(Other)": auth_svc.create_access_token(user_id="660000000000000000000008", role=UserRole.DOCTOR.value)[0],
        "Doctor_(Unverified)": auth_svc.create_access_token(user_id="660000000000000000000009", role=UserRole.DOCTOR.value)[0],
        "Coord_(Own_Hosp)": auth_svc.create_access_token(user_id="66000000000000000000000a", role=UserRole.HOSPITAL_COORDINATOR.value)[0],
        "Coord_(Other_Hosp)": auth_svc.create_access_token(user_id="66000000000000000000000b", role=UserRole.HOSPITAL_COORDINATOR.value)[0],
        "Admin": auth_svc.create_access_token(user_id="66000000000000000000000c", role=UserRole.ADMIN.value)[0],
    }

    # 3. Patient Profiles
    p_owner_profile = await patient_svc.create_patient(
        created_by="660000000000000000000001", date_of_birth="1985-05-15", user_id="660000000000000000000001"
    )
    await patient_svc.create_patient(
        created_by="660000000000000000000002", date_of_birth="1992-08-20", user_id="660000000000000000000002"
    )
    scr_created_profile = await patient_svc.create_patient(
        created_by="660000000000000000000003", date_of_birth="1988-03-12"
    )

    # 4. Target Cases
    # Case A: Assigned case in under_review
    case_a = await case_svc.create_case_draft(patient_id=p_owner_profile.id, created_by="660000000000000000000003")
    await db["cases"].update_one(
        {"_id": ObjectId(case_a.id)},
        {
            "$set": {
                "status": CaseStatus.UNDER_REVIEW.value,
                "assigned_doctor_id": "660000000000000000000005",
                "second_opinion_doctor_id": "660000000000000000000006",
            }
        },
    )

    # Case B: Pool Case (ai_analyzed, unassigned)
    case_b_pool = await case_svc.create_case_draft(patient_id=p_owner_profile.id, created_by="660000000000000000000001")
    await db["cases"].update_one(
        {"_id": ObjectId(case_b_pool.id)},
        {
            "$set": {
                "status": CaseStatus.AI_ANALYZED.value,
                "assigned_doctor_id": None,
            }
        },
    )

    # 5. Resolve target URL and payload
    if target_spec == "TARGET_CASE_A":
        url = f"/cases/{case_a.id}"
    elif target_spec == "TARGET_CASE_A_TIMELINE":
        url = f"/cases/{case_a.id}/timeline"
    elif target_spec == "TARGET_CASE_B_POOL":
        url = f"/cases/{case_b_pool.id}"
    else:
        url = target_spec

    if payload_spec == "DYNAMIC_CASE_PAYLOAD":
        payload = {"patient_id": scr_created_profile.id}
    elif payload_spec == "DYNAMIC_CONSENT_PAYLOAD":
        payload = {
            "patient_id": p_owner_profile.id,
            "consent_version": "v1",
            "consent_accepted": True,
        }
    else:
        payload = payload_spec

    # 6. Execute Request
    headers = {}
    tok = tokens.get(persona)
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    if method == "GET":
        res = await async_client.get(url, headers=headers)
    elif method == "POST":
        res = await async_client.post(url, headers=headers, json=payload)
    else:
        raise ValueError(f"Unsupported method: {method}")

    assert res.status_code == expected_status, (
        f"Cell [{name} | {persona}] failed: expected {expected_status}, "
        f"got {res.status_code} ({res.text})"
    )
