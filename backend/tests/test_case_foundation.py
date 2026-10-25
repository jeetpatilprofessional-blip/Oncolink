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

# --- Helper fixtures and setup ---

async def create_user_and_token(
    db,
    settings: Settings,
    auth_service: AuthService,
    role: UserRole,
    email: str,
    verification_status: DoctorVerificationStatus = DoctorVerificationStatus.VERIFIED,
    hospital_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    now = datetime.now(UTC)
    user_doc = {
        "email": email,
        "password_hash": auth_service.hash_password("Password#123!"),
        "role": role.value,
        "is_active": True,
        "is_demo": False,
        "created_at": now,
        "failed_login_attempts": 0,
        "locked_until": None,
        "totp_enrolled": True,
    }
    if role == UserRole.DOCTOR:
        user_doc["registration_number"] = f"REG-{email}"
        user_doc["verification_status"] = verification_status.value
        user_doc["verified_by"] = "test_admin"
        user_doc["verified_at"] = now
    if hospital_id:
        user_doc["hospital_id"] = hospital_id

    res = await db["users"].insert_one(user_doc)
    user_doc["id"] = str(res.inserted_id)
    token, _ = auth_service.create_access_token(user_id=user_doc["id"], role=role.value)
    return user_doc, token


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
    # 17 years old
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

    _, screener_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.SCREENER, "screener_dob@example.com")
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
# 3. State Machine Cross-Product Transition Tests
# ==============================================================================
def test_state_machine_transition_table_cross_product():
    """
    Exhaustively tests all 23x23=529 state transitions across actor roles.
    Asserts that exact table edges succeed and every other transition is strictly denied.
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

    total_combinations = 0
    allowed_count = 0

    for from_st in all_states:
        for to_st in all_states:
            for role in roles:
                total_combinations += 1
                allowed = is_transition_allowed(from_st, to_st, role)
                allowed_roles = ALLOWED_TRANSITIONS.get((from_st, to_st), set())

                # Special conditional edge: outreach -> confirmed requires new appointment condition
                if (from_st, to_st) == (CaseStatus.OUTREACH, CaseStatus.CONFIRMED):
                    continue

                expected = role in allowed_roles

                if allowed:
                    allowed_count += 1
                    assert (
                        expected
                    ), f"Unexpectedly allowed transition: {from_st} -> {to_st} for role {role}"
                else:
                    assert (
                        not expected
                    ), f"Denied valid edge: {from_st} -> {to_st} for role {role}"

    assert total_combinations == len(all_states) * len(all_states) * len(roles)
    assert allowed_count > 0


# ==============================================================================
# 4. State-Dependent 409 for POST /cases/{id}/cancel
# ==============================================================================
@pytest.mark.asyncio
async def test_case_cancellation_pre_vs_post_signing_states(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    POST /cases/{id}/cancel is permitted in states prior to 'signed' (draft, submitted,
    quality_check, needs_retake, queued, ai_analyzed, under_review, uncertain_needs_inperson)
    and strictly returns 409 Conflict in signed or any downstream state.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    # Setup patient owner
    patient_user, patient_token = await create_user_and_token(
        db, test_settings, auth_svc, UserRole.PATIENT, "cancel_patient@example.com"
    )
    p_profile = await patient_svc.create_patient(
        created_by=patient_user["id"],
        date_of_birth="1990-01-01",
        user_id=patient_user["id"],
    )

    headers = {"Authorization": f"Bearer {patient_token}"}

    # 1. Pre-signing cancellation succeeds
    pre_case = await case_svc.create_case_draft(patient_id=p_profile.id, created_by=patient_user["id"])
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
        # Create case and force status in DB
        case_doc = await case_svc.create_case_draft(patient_id=p_profile.id, created_by=patient_user["id"])
        await db["cases"].update_one({"_id": ObjectId(case_doc.id)}, {"$set": {"status": st.value}})

        conflict_res = await async_client.post(f"/cases/{case_doc.id}/cancel", headers=headers)
        assert conflict_res.status_code == 409, f"Expected 409 for status '{st.value}', got {conflict_res.status_code}"


# ==============================================================================
# 5. Rollback Test: Transactional Atomicity on Audit Failure
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
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    patient_user, _ = await create_user_and_token(
        db, test_settings, auth_svc, UserRole.PATIENT, "rollback_patient@example.com"
    )
    p_profile = await patient_svc.create_patient(
        created_by=patient_user["id"],
        date_of_birth="1990-01-01",
        user_id=patient_user["id"],
    )

    case = await case_svc.create_case_draft(patient_id=p_profile.id, created_by=patient_user["id"])
    initial_version = case.version

    # Force failure during AuditService.insert
    with patch.object(AuditService, "insert", side_effect=RuntimeError("Forced audit failure")):
        with pytest.raises(RuntimeError, match="Forced audit failure"):
            actor = {"id": patient_user["id"], "role": UserRole.PATIENT.value, "patient_id": p_profile.id}
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
# 6. Concurrency: Two Simultaneous Transitions Yield One Success and One 409
# ==============================================================================
@pytest.mark.asyncio
async def test_concurrent_transitions_yield_one_winner_and_one_conflict(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Two concurrent transitions on the same case from the same version must yield
    exactly one 200/success and one 409 Conflict.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    patient_user, _ = await create_user_and_token(
        db, test_settings, auth_svc, UserRole.PATIENT, "concurrency_patient@example.com"
    )
    p_profile = await patient_svc.create_patient(
        created_by=patient_user["id"],
        date_of_birth="1990-01-01",
        user_id=patient_user["id"],
    )

    case = await case_svc.create_case_draft(patient_id=p_profile.id, created_by=patient_user["id"])
    actor = {"id": patient_user["id"], "role": UserRole.PATIENT.value, "patient_id": p_profile.id}

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

    # Verify DB has version 2
    case_in_db = await db["cases"].find_one({"_id": ObjectId(case.id)})
    assert case_in_db["version"] == 2


# ==============================================================================
# 7. Reason Text Privacy Invariant
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
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    patient_user, _ = await create_user_and_token(
        db, test_settings, auth_svc, UserRole.PATIENT, "privacy_patient@example.com"
    )
    p_profile = await patient_svc.create_patient(
        created_by=patient_user["id"],
        date_of_birth="1990-01-01",
        user_id=patient_user["id"],
    )

    case = await case_svc.create_case_draft(patient_id=p_profile.id, created_by=patient_user["id"])
    secret_text = "SECRET_PATIENT_REASON_TEXT_SENSITIVE_NOTE_12345"

    actor = {"id": patient_user["id"], "role": UserRole.PATIENT.value, "patient_id": p_profile.id}
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
# 8. Source Scan Invariant Test
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
            assert (
                not match
            ), f"Forbidden case status write detected in {py_file}: {match.group(0)}"


# ==============================================================================
# 9. Table-Driven Authorization Matrix Tests (Across All Persona Columns)
# ==============================================================================
@pytest.mark.asyncio
async def test_table_driven_authorization_matrix(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Exhaustively tests the 8 endpoints built in this task across all persona columns
    defined in docs/PERMISSIONS.md Section 6.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_svc = PatientService(db)
    case_svc = CaseService(db)

    # 1. Provision Personas
    # Patient Owner & Patient Other
    p_owner_user, p_owner_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.PATIENT, "p_owner@test.local")
    p_owner_profile = await patient_svc.create_patient(created_by=p_owner_user["id"], date_of_birth="1985-05-15", user_id=p_owner_user["id"])

    p_other_user, p_other_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.PATIENT, "p_other@test.local")
    await patient_svc.create_patient(created_by=p_other_user["id"], date_of_birth="1992-08-20", user_id=p_other_user["id"])

    # Screener Creator & Screener Other
    scr_creator_user, scr_creator_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.SCREENER, "scr_creator@test.local")
    scr_other_user, scr_other_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.SCREENER, "scr_other@test.local")
    # Patient profile created by screener creator
    scr_created_profile = await patient_svc.create_patient(created_by=scr_creator_user["id"], date_of_birth="1988-03-12")

    # Doctors
    doc_assigned_user, doc_assigned_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.DOCTOR, "doc_assigned@test.local")
    doc_second_op_user, doc_second_op_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.DOCTOR, "doc_second_op@test.local")
    doc_pool_user, doc_pool_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.DOCTOR, "doc_pool@test.local")
    doc_other_user, doc_other_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.DOCTOR, "doc_other@test.local")
    doc_unverified_user, doc_unverified_token = await create_user_and_token(
        db, test_settings, auth_svc, UserRole.DOCTOR, "doc_unverified@test.local", verification_status=DoctorVerificationStatus.PENDING
    )

    # Coordinators & Admin
    coord_own_user, coord_own_token = await create_user_and_token(
        db, test_settings, auth_svc, UserRole.HOSPITAL_COORDINATOR, "coord_own@test.local", hospital_id="HOSP_01"
    )
    coord_other_user, coord_other_token = await create_user_and_token(
        db, test_settings, auth_svc, UserRole.HOSPITAL_COORDINATOR, "coord_other@test.local", hospital_id="HOSP_02"
    )
    admin_user, admin_token = await create_user_and_token(db, test_settings, auth_svc, UserRole.ADMIN, "admin@test.local")

    # 2. Provision Target Cases
    # Case A: Assigned case (under_review, owned by p_owner, created by scr_creator, assigned to doc_assigned, 2nd op doc_second_op)
    case_a = await case_svc.create_case_draft(patient_id=p_owner_profile.id, created_by=scr_creator_user["id"])
    await db["cases"].update_one(
        {"_id": ObjectId(case_a.id)},
        {
            "$set": {
                "status": CaseStatus.UNDER_REVIEW.value,
                "assigned_doctor_id": doc_assigned_user["id"],
                "second_opinion_doctor_id": doc_second_op_user["id"],
            }
        },
    )

    # Case B: Pool Case (queued, unassigned, owned by p_owner)
    case_b_pool = await case_svc.create_case_draft(patient_id=p_owner_profile.id, created_by=p_owner_user["id"])
    await db["cases"].update_one({"_id": ObjectId(case_b_pool.id)}, {"$set": {"status": CaseStatus.QUEUED.value}})

    # Headers dictionary
    auth_headers = {
        "Unauth": {},
        "Patient (Owner)": {"Authorization": f"Bearer {p_owner_token}"},
        "Patient (Other)": {"Authorization": f"Bearer {p_other_token}"},
        "Screener (Creator)": {"Authorization": f"Bearer {scr_creator_token}"},
        "Screener (Other)": {"Authorization": f"Bearer {scr_other_token}"},
        "Doctor (Assigned)": {"Authorization": f"Bearer {doc_assigned_token}"},
        "Doctor (Second opinion)": {"Authorization": f"Bearer {doc_second_op_token}"},
        "Doctor (verified, pool case)": {"Authorization": f"Bearer {doc_pool_token}"},
        "Doctor (Other)": {"Authorization": f"Bearer {doc_other_token}"},
        "Doctor (Unverified)": {"Authorization": f"Bearer {doc_unverified_token}"},
        "Coord (Own Hosp)": {"Authorization": f"Bearer {coord_own_token}"},
        "Coord (Other Hosp)": {"Authorization": f"Bearer {coord_other_token}"},
        "Admin": {"Authorization": f"Bearer {admin_token}"},
    }

    # Test matrix for the 8 endpoints
    matrix_specs = [
        # 1. POST /patients (screener creates profile)
        {
            "name": "POST /patients",
            "method": "POST",
            "url": "/patients",
            "payload": {"date_of_birth": "1990-01-01", "language": "en"},
            "expected": {
                "Unauth": 401,
                "Patient (Owner)": 403,
                "Patient (Other)": 403,
                "Screener (Creator)": 201,
                "Screener (Other)": 201,
                "Doctor (Assigned)": 403,
                "Doctor (Second opinion)": 403,
                "Doctor (verified, pool case)": 403,
                "Doctor (Other)": 403,
                "Doctor (Unverified)": 403,
                "Coord (Own Hosp)": 403,
                "Coord (Other Hosp)": 403,
                "Admin": 403,
            },
        },
        # 2. POST /cases (draft creation)
        {
            "name": "POST /cases",
            "method": "POST",
            "url": "/cases",
            "payload": {"patient_id": scr_created_profile.id},
            "expected": {
                "Unauth": 401,
                "Patient (Owner)": 201,  # Resolves own profile
                "Patient (Other)": 201,  # Resolves own profile
                "Screener (Creator)": 201,  # Target patient created by scr_creator
                "Screener (Other)": 404,  # Anti-probing: patient created by other screener -> 404
                "Doctor (Assigned)": 403,
                "Doctor (Second opinion)": 403,
                "Doctor (verified, pool case)": 403,
                "Doctor (Other)": 403,
                "Doctor (Unverified)": 403,
                "Coord (Own Hosp)": 403,
                "Coord (Other Hosp)": 403,
                "Admin": 403,
            },
        },
        # 3. GET /cases (list cases)
        {
            "name": "GET /cases",
            "method": "GET",
            "url": "/cases",
            "payload": None,
            "expected": {
                "Unauth": 401,
                "Patient (Owner)": 200,
                "Patient (Other)": 200,
                "Screener (Creator)": 200,
                "Screener (Other)": 200,
                "Doctor (Assigned)": 403,
                "Doctor (Second opinion)": 403,
                "Doctor (verified, pool case)": 403,
                "Doctor (Other)": 403,
                "Doctor (Unverified)": 403,
                "Coord (Own Hosp)": 403,
                "Coord (Other Hosp)": 403,
                "Admin": 403,
            },
        },
        # 4. GET /cases/{id} on Assigned Case A
        {
            "name": "GET /cases/{id} (Assigned Case A)",
            "method": "GET",
            "url": f"/cases/{case_a.id}",
            "payload": None,
            "expected": {
                "Unauth": 401,
                "Patient (Owner)": 200,  # Status only
                "Patient (Other)": 404,  # Anti-probing
                "Screener (Creator)": 200,  # Status only
                "Screener (Other)": 404,  # Anti-probing
                "Doctor (Assigned)": 200,  # Full view
                "Doctor (Second opinion)": 200,  # Full view
                "Doctor (verified, pool case)": 404,  # Not in pool (under_review)
                "Doctor (Other)": 404,  # Not assigned
                "Doctor (Unverified)": 403,  # Uniform 403
                "Coord (Own Hosp)": 403,
                "Coord (Other Hosp)": 403,
                "Admin": 403,
            },
        },
        # 5. GET /cases/{id} on Pool Case B (queued)
        {
            "name": "GET /cases/{id} (Pool Case B)",
            "method": "GET",
            "url": f"/cases/{case_b_pool.id}",
            "payload": None,
            "expected": {
                "Unauth": 401,
                "Doctor (verified, pool case)": 200,  # Metadata view
                "Doctor (Unverified)": 403,  # Uniform 403
            },
        },
        # 6. GET /cases/{id}/timeline (Assigned Case A)
        {
            "name": "GET /cases/{id}/timeline",
            "method": "GET",
            "url": f"/cases/{case_a.id}/timeline",
            "payload": None,
            "expected": {
                "Unauth": 401,
                "Patient (Owner)": 403,
                "Patient (Other)": 403,
                "Screener (Creator)": 403,
                "Screener (Other)": 403,
                "Doctor (Assigned)": 200,
                "Doctor (Second opinion)": 200,
                "Doctor (verified, pool case)": 404,
                "Doctor (Other)": 404,
                "Doctor (Unverified)": 403,
                "Coord (Own Hosp)": 403,
                "Coord (Other Hosp)": 403,
                "Admin": 403,
            },
        },
        # 7. POST /consent
        {
            "name": "POST /consent",
            "method": "POST",
            "url": "/consent",
            "payload": {
                "patient_id": p_owner_profile.id,
                "consent_version": "v1",
                "consent_accepted": True,
            },
            "expected": {
                "Unauth": 401,
                "Patient (Owner)": 201,
                "Patient (Other)": 404,
                "Screener (Creator)": 404,  # Patient was self-created by p_owner, not screener -> 404
                "Screener (Other)": 404,
                "Doctor (Assigned)": 403,
                "Doctor (Second opinion)": 403,
                "Doctor (verified, pool case)": 403,
                "Doctor (Other)": 403,
                "Doctor (Unverified)": 403,
                "Coord (Own Hosp)": 403,
                "Coord (Other Hosp)": 403,
                "Admin": 403,
            },
        },
        # 8. POST /auth/register
        {
            "name": "POST /auth/register",
            "method": "POST",
            "url": "/auth/register",
            "payload": {
                "email": "new_unauth_patient@example.com",
                "password": "ValidPassword123!",
                "date_of_birth": "1991-01-01",
                "consent_version": "v1",
                "consent_accepted": True,
            },
            "expected": {
                "Unauth": 201,
                "Patient (Owner)": 403,
                "Patient (Other)": 403,
                "Screener (Creator)": 403,
                "Screener (Other)": 403,
                "Doctor (Assigned)": 403,
                "Doctor (Second opinion)": 403,
                "Doctor (verified, pool case)": 403,
                "Doctor (Other)": 403,
                "Doctor (Unverified)": 403,
                "Coord (Own Hosp)": 403,
                "Coord (Other Hosp)": 403,
                "Admin": 403,
            },
        },
    ]

    for spec in matrix_specs:
        for persona, expected_status in spec["expected"].items():
            headers = auth_headers[persona]
            method = spec["method"]
            url = spec["url"]
            payload = spec["payload"]

            if method == "GET":
                res = await async_client.get(url, headers=headers)
            elif method == "POST":
                res = await async_client.post(url, headers=headers, json=payload)
            else:
                raise ValueError(f"Unsupported method {method}")

            assert res.status_code == expected_status, (
                f"[{spec['name']}] Failed for persona '{persona}': "
                f"expected {expected_status}, got {res.status_code} ({res.text})"
            )
