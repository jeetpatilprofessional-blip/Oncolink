from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClientSession, AsyncIOMotorDatabase
from pymongo.errors import OperationFailure

from app.database import get_database, run_transaction
from app.models.case import CaseStatus, ReasonCode
from app.models.user import DoctorVerificationStatus, UserInDB, UserRole
from app.services.audit_service import AuditService

# --- Authoritative Transition Table from docs/SPEC.md Section 4 ---
# Mapping: (from_state, to_state) -> set of allowed actor roles
ALLOWED_TRANSITIONS: dict[tuple[CaseStatus, CaseStatus], set[str]] = {
    # 1. draft -> submitted (Patient, Screener)
    (CaseStatus.DRAFT, CaseStatus.SUBMITTED): {UserRole.PATIENT.value, UserRole.SCREENER.value},
    # 2. submitted -> quality_check (System)
    (CaseStatus.SUBMITTED, CaseStatus.QUALITY_CHECK): {"system"},
    # 3. submitted -> red_flag (System)
    (CaseStatus.SUBMITTED, CaseStatus.RED_FLAG): {"system"},
    # 3b. quality_check -> red_flag (System)
    (CaseStatus.QUALITY_CHECK, CaseStatus.RED_FLAG): {"system"},
    # 4. quality_check -> needs_retake (System)
    (CaseStatus.QUALITY_CHECK, CaseStatus.NEEDS_RETAKE): {"system"},
    # 5. quality_check -> queued (System)
    (CaseStatus.QUALITY_CHECK, CaseStatus.QUEUED): {"system"},
    # 6. needs_retake -> submitted (Patient, Screener)
    (CaseStatus.NEEDS_RETAKE, CaseStatus.SUBMITTED): {
        UserRole.PATIENT.value,
        UserRole.SCREENER.value,
    },
    # 7. queued -> ai_analyzed (System)
    (CaseStatus.QUEUED, CaseStatus.AI_ANALYZED): {"system"},
    # 8. ai_analyzed -> under_review (Doctor, System)
    (CaseStatus.AI_ANALYZED, CaseStatus.UNDER_REVIEW): {UserRole.DOCTOR.value, "system"},
    # 9. under_review -> ai_analyzed (Doctor voluntary release; retains AI result)
    (CaseStatus.UNDER_REVIEW, CaseStatus.AI_ANALYZED): {UserRole.DOCTOR.value},
    # 10. under_review -> needs_retake (Doctor)
    (CaseStatus.UNDER_REVIEW, CaseStatus.NEEDS_RETAKE): {UserRole.DOCTOR.value},
    # 11. under_review -> uncertain_needs_inperson (Doctor)
    (CaseStatus.UNDER_REVIEW, CaseStatus.UNCERTAIN_NEEDS_INPERSON): {UserRole.DOCTOR.value},
    # 12. under_review -> signed (Doctor)
    (CaseStatus.UNDER_REVIEW, CaseStatus.SIGNED): {UserRole.DOCTOR.value},
    # 13. signed -> closed_monitor (Doctor)
    (CaseStatus.SIGNED, CaseStatus.CLOSED_MONITOR): {UserRole.DOCTOR.value},
    # 14. signed -> referred (Doctor)
    (CaseStatus.SIGNED, CaseStatus.REFERRED): {UserRole.DOCTOR.value},
    # 15. referred -> referral_pending (System)
    (CaseStatus.REFERRED, CaseStatus.REFERRAL_PENDING): {"system"},
    # 16. referral_pending -> confirmed (Hospital Coordinator)
    (CaseStatus.REFERRAL_PENDING, CaseStatus.CONFIRMED): {UserRole.HOSPITAL_COORDINATOR.value},
    # 17. referral_pending -> declined_by_hospital (Hospital Coordinator)
    (CaseStatus.REFERRAL_PENDING, CaseStatus.DECLINED_BY_HOSPITAL): {
        UserRole.HOSPITAL_COORDINATOR.value
    },
    # 18. declined_by_hospital -> referred (Doctor)
    (CaseStatus.DECLINED_BY_HOSPITAL, CaseStatus.REFERRED): {UserRole.DOCTOR.value},
    # 19. confirmed -> attended (Hospital Coordinator)
    (CaseStatus.CONFIRMED, CaseStatus.ATTENDED): {UserRole.HOSPITAL_COORDINATOR.value},
    # 20. confirmed -> no_show (Hospital Coordinator)
    (CaseStatus.CONFIRMED, CaseStatus.NO_SHOW): {UserRole.HOSPITAL_COORDINATOR.value},
    # 21. no_show -> outreach (System, Screener)
    (CaseStatus.NO_SHOW, CaseStatus.OUTREACH): {"system", UserRole.SCREENER.value},
    # 22. outreach -> confirmed (Hospital Coordinator) - requires new appointment
    (CaseStatus.OUTREACH, CaseStatus.CONFIRMED): {UserRole.HOSPITAL_COORDINATOR.value},
    # 23. outreach -> lost_to_followup (System, Hospital Coordinator)
    (CaseStatus.OUTREACH, CaseStatus.LOST_TO_FOLLOWUP): {
        "system",
        UserRole.HOSPITAL_COORDINATOR.value,
    },
    # 24. attended -> outcome_recorded (Hospital Coordinator)
    (CaseStatus.ATTENDED, CaseStatus.OUTCOME_RECORDED): {UserRole.HOSPITAL_COORDINATOR.value},
    # 25. outcome_recorded -> closed (System, Hospital Coordinator)
    (CaseStatus.OUTCOME_RECORDED, CaseStatus.CLOSED): {
        "system",
        UserRole.HOSPITAL_COORDINATOR.value,
    },
}

# 26. Cancelled: Allowed strictly prior to signed from the 8 pre-signing states
CANCELLABLE_STATES = (
    CaseStatus.DRAFT,
    CaseStatus.SUBMITTED,
    CaseStatus.QUALITY_CHECK,
    CaseStatus.NEEDS_RETAKE,
    CaseStatus.QUEUED,
    CaseStatus.AI_ANALYZED,
    CaseStatus.UNDER_REVIEW,
    CaseStatus.UNCERTAIN_NEEDS_INPERSON,
)
for _s in CANCELLABLE_STATES:
    ALLOWED_TRANSITIONS[(_s, CaseStatus.CANCELLED)] = {
        UserRole.PATIENT.value,
        UserRole.SCREENER.value,
    }

# 27. consent_withdrawn: Reachable from ANY state via patient right to be forgotten or automated data erasure
for _s in CaseStatus:
    ALLOWED_TRANSITIONS[(_s, CaseStatus.CONSENT_WITHDRAWN)] = {
        UserRole.PATIENT.value,
        "system",
    }


def is_transition_allowed(
    from_state: CaseStatus,
    to_state: CaseStatus,
    actor_role: str,
    extra_conditions: dict[str, Any] | None = None,
) -> bool:
    """
    Evaluates whether a state transition edge is legal according to SPEC Section 4.
    Returns True if permitted; False otherwise.
    """
    allowed_roles = ALLOWED_TRANSITIONS.get((from_state, to_state))
    if not allowed_roles or actor_role not in allowed_roles:
        return False

    # Extra condition: outreach -> confirmed requires appointment to exist
    if from_state == CaseStatus.OUTREACH and to_state == CaseStatus.CONFIRMED:
        if not (extra_conditions and extra_conditions.get("new_appointment_exists")):
            return False

    return True


async def transition(
    case_id: str | ObjectId,
    to_state: CaseStatus | str,
    actor: UserInDB | dict[str, Any],
    reason_code: ReasonCode | str,
    reason_text: str | None = None,
    *,
    db: AsyncIOMotorDatabase | None = None,
    extra_conditions: dict[str, Any] | None = None,
    assigned_doctor_id: str | None = None,
) -> dict[str, Any]:
    """
    Executes an atomic case status transition within ONE MongoDB transaction.

    Security & Invariant Guarantees:
    1. Only the state machine service may write case status in the entire codebase.
    2. Enforces optimistic concurrency control via integer 'version' counter (stale writes get 409).
    3. Records status_history entry containing (from, to, actor, time, reason_code, reason_text).
    4. Writes audit entry containing IDs and reason_code ONLY, NEVER reason_text.
    5. Illegal transitions return 409 Conflict.
    6. If the audit insertion fails, the entire transaction rolls back automatically.
    """
    target_db = db if db is not None else get_database()
    target_state = CaseStatus(to_state) if isinstance(to_state, str) else to_state
    norm_reason_code = reason_code.value if hasattr(reason_code, "value") else str(reason_code)

    # Normalize actor identity and role
    if isinstance(actor, UserInDB):
        actor_id = str(actor.id)
        actor_role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        is_verified_doc = (
            actor.role == UserRole.DOCTOR
            and actor.verification_status == DoctorVerificationStatus.VERIFIED
        )
    elif isinstance(actor, dict):
        actor_id = str(actor.get("id", "system"))
        actor_role = str(actor.get("role", "system"))
        is_verified_doc = actor.get("is_verified", True)
    else:
        actor_id = getattr(actor, "id", "system")
        actor_role = str(getattr(actor, "role", "system"))
        is_verified_doc = (
            getattr(actor, "verification_status", None) == DoctorVerificationStatus.VERIFIED
        )

    # Gate 2: Unverified doctors are blocked uniformly
    if actor_role == UserRole.DOCTOR.value and not is_verified_doc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor is unverified. All clinical status transitions are forbidden.",
        )

    case_oid = ObjectId(case_id) if ObjectId.is_valid(str(case_id)) else case_id

    async def _execute_tx(session: AsyncIOMotorClientSession) -> dict[str, Any]:
        # 1. Fetch current case document inside the transaction session
        case_doc = await target_db["cases"].find_one({"_id": case_oid}, session=session)
        if not case_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case '{case_id}' not found.",
            )

        from_state = CaseStatus(case_doc["status"])
        current_version = int(case_doc.get("version", 1))

        # 2. Ownership & role assignment checks (Anti-Probing & Authorization Invariants)
        if actor_role == UserRole.PATIENT.value:
            # Patient must own this case
            caller_patient_id = getattr(actor, "patient_id", None) or (
                actor.get("patient_id") if isinstance(actor, dict) else None
            )
            if not caller_patient_id:
                patient_rec = await target_db["patients"].find_one(
                    {"user_id": actor_id, "erased": False}, session=session
                )
                caller_patient_id = str(patient_rec["_id"]) if patient_rec else None

            if (
                case_doc.get("patient_id") != caller_patient_id
                and case_doc.get("created_by") != actor_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Case not found",
                )

        elif actor_role == UserRole.SCREENER.value:
            # Screener must have created this case
            if case_doc.get("created_by") != actor_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Case not found",
                )

        elif actor_role == UserRole.DOCTOR.value:
            # Assigned doctor transitions require the caller to be the primary assigned doctor
            assigned_doc_id = case_doc.get("assigned_doctor_id")
            if from_state in (
                CaseStatus.UNDER_REVIEW,
                CaseStatus.SIGNED,
                CaseStatus.DECLINED_BY_HOSPITAL,
            ):
                if assigned_doc_id and assigned_doc_id != actor_id:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Case not found",
                    )
            elif from_state == CaseStatus.AI_ANALYZED and target_state == CaseStatus.UNDER_REVIEW:
                # Claiming from unassigned pool
                if assigned_doc_id is not None:
                    # Already assigned
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Case is already claimed by another clinician.",
                    )

        # 3. Check transition legality
        if not is_transition_allowed(from_state, target_state, actor_role, extra_conditions):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Illegal state transition from '{from_state.value}' to '{target_state.value}' "
                    f"for actor role '{actor_role}'."
                ),
            )

        now = datetime.now(UTC)
        next_version = current_version + 1

        # 4. Construct status_history entry (includes reason_text strictly for case history)
        history_entry = {
            "from_status": from_state.value,
            "to_status": target_state.value,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "timestamp": now,
            "reason_code": norm_reason_code,
            "reason_text": reason_text,
        }

        # 5. Build $set update payload
        set_payload: dict[str, Any] = {
            "status": target_state.value,
            "version": next_version,
            "updated_at": now,
        }
        if assigned_doctor_id is not None:
            set_payload["assigned_doctor_id"] = assigned_doctor_id
        elif (
            target_state == CaseStatus.UNDER_REVIEW
            and from_state == CaseStatus.AI_ANALYZED
            and actor_role == UserRole.DOCTOR.value
        ):
            set_payload["assigned_doctor_id"] = actor_id
        elif target_state == CaseStatus.AI_ANALYZED and from_state == CaseStatus.UNDER_REVIEW:
            # Voluntary release unassigns the doctor while keeping AI result
            set_payload["assigned_doctor_id"] = None

        # 6. Execute atomic update with optimistic version filter
        update_filter = {
            "_id": case_doc["_id"],
            "version": current_version,
            "status": from_state.value,
        }
        update_result = await target_db["cases"].update_one(
            update_filter,
            {
                "$set": set_payload,
                "$push": {"status_history": history_entry},
            },
            session=session,
        )

        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Concurrent modification conflict: case was modified by another operation.",
            )

        # 7. Write immutable audit log entry (IDs and reason_code ONLY, NEVER reason_text)
        audit_service = AuditService(target_db)
        await audit_service.insert(
            event_type="case_status_transition",
            actor_id=actor_id,
            actor_role=actor_role,
            target_user_id=str(case_doc.get("patient_id", "")),
            details={
                "case_id": str(case_doc["_id"]),
                "reference": case_doc.get("reference", ""),
                "from_status": from_state.value,
                "to_status": target_state.value,
                "reason_code": norm_reason_code,
            },
            session=session,
        )

        # Return updated snapshot
        case_doc["status"] = target_state.value
        case_doc["version"] = next_version
        case_doc["updated_at"] = now
        case_doc["status_history"].append(history_entry)
        if "assigned_doctor_id" in set_payload:
            case_doc["assigned_doctor_id"] = set_payload["assigned_doctor_id"]
        return case_doc

    try:
        return await run_transaction(target_db.client, _execute_tx)
    except OperationFailure as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Concurrent modification conflict: {err}",
        ) from err


async def transition_chain(
    case_id: str | ObjectId,
    steps: list[tuple[CaseStatus | str, ReasonCode | str, str | None, str]],
    actor: UserInDB | dict[str, Any],
    *,
    db: AsyncIOMotorDatabase | None = None,
    extra_case_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Executes an atomic sequence of state transitions within ONE single MongoDB transaction.
    Writes one status_history record and one immutable audit entry per transition edge.

    Atomicity Invariant:
    If any step or audit insertion fails mid-chain, the entire transaction rolls back automatically,
    leaving the case document in its initial state with zero partial transitions.
    """
    target_db = db if db is not None else get_database()
    case_oid = ObjectId(case_id) if ObjectId.is_valid(str(case_id)) else case_id

    # Normalize caller actor
    if isinstance(actor, UserInDB):
        caller_actor_id = str(actor.id)
        caller_actor_role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
    elif isinstance(actor, dict):
        caller_actor_id = str(actor.get("id", "system"))
        caller_actor_role = str(actor.get("role", "system"))
    else:
        caller_actor_id = getattr(actor, "id", "system")
        caller_actor_role = str(getattr(actor, "role", "system"))

    async def _execute_chain_tx(session: AsyncIOMotorClientSession) -> dict[str, Any]:
        case_doc = await target_db["cases"].find_one({"_id": case_oid}, session=session)
        if not case_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Case '{case_id}' not found.",
            )

        initial_status = CaseStatus(case_doc["status"])
        initial_version = int(case_doc.get("version", 1))

        current_state = initial_status
        now = datetime.now(UTC)
        new_history_entries: list[dict[str, Any]] = []
        audit_service = AuditService(target_db)

        # Enforce caller ownership on initial state
        if caller_actor_role == UserRole.PATIENT.value:
            caller_patient_id = getattr(actor, "patient_id", None) or (
                actor.get("patient_id") if isinstance(actor, dict) else None
            )
            if not caller_patient_id:
                patient_rec = await target_db["patients"].find_one(
                    {"user_id": caller_actor_id, "erased": False}, session=session
                )
                caller_patient_id = str(patient_rec["_id"]) if patient_rec else None

            if (
                case_doc.get("patient_id") != caller_patient_id
                and case_doc.get("created_by") != caller_actor_id
            ):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

        elif caller_actor_role == UserRole.SCREENER.value:
            if case_doc.get("created_by") != caller_actor_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

        for to_state, reason_code, reason_text, step_actor_role in steps:
            target_state = CaseStatus(to_state) if isinstance(to_state, str) else to_state
            norm_code = reason_code.value if hasattr(reason_code, "value") else str(reason_code)

            if not is_transition_allowed(current_state, target_state, step_actor_role):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Illegal state transition from '{current_state.value}' to '{target_state.value}' "
                        f"for actor role '{step_actor_role}'."
                    ),
                )

            step_actor_id = caller_actor_id if step_actor_role == caller_actor_role else "system"

            hist_entry = {
                "from_status": current_state.value,
                "to_status": target_state.value,
                "actor_id": step_actor_id,
                "actor_role": step_actor_role,
                "timestamp": now,
                "reason_code": norm_code,
                "reason_text": reason_text,
            }
            new_history_entries.append(hist_entry)

            # Insert immutable audit entry per edge (structural IDs and reason_code ONLY)
            await audit_service.insert(
                event_type="case_status_transition",
                actor_id=step_actor_id,
                actor_role=step_actor_role,
                target_user_id=str(case_doc.get("patient_id", "")),
                details={
                    "case_id": str(case_doc["_id"]),
                    "reference": case_doc.get("reference", ""),
                    "from_status": current_state.value,
                    "to_status": target_state.value,
                    "reason_code": norm_code,
                },
                session=session,
            )

            current_state = target_state

        final_version = initial_version + len(steps)
        set_payload: dict[str, Any] = {
            "status": current_state.value,
            "version": final_version,
            "updated_at": now,
        }
        if extra_case_updates:
            set_payload.update(extra_case_updates)

        update_filter = {
            "_id": case_doc["_id"],
            "version": initial_version,
            "status": initial_status.value,
        }
        update_result = await target_db["cases"].update_one(
            update_filter,
            {
                "$set": set_payload,
                "$push": {"status_history": {"$each": new_history_entries}},
            },
            session=session,
        )

        if update_result.modified_count == 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Concurrent modification conflict: case was modified by another operation.",
            )

        case_doc["status"] = current_state.value
        case_doc["version"] = final_version
        case_doc["updated_at"] = now
        case_doc["status_history"].extend(new_history_entries)
        if extra_case_updates:
            case_doc.update(extra_case_updates)

        return case_doc

    try:
        return await run_transaction(target_db.client, _execute_chain_tx)
    except OperationFailure as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Concurrent modification conflict: {err}",
        ) from err
