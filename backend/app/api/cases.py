from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import (
    get_case_service,
    get_current_user,
    get_db,
    get_patient_service,
)
from app.models.case import (
    CaseCancelRequest,
    CaseCreateRequest,
    CaseDetailResponse,
    CasePoolMetadataResponse,
    CaseStatus,
    CaseStatusResponse,
    CaseTimelineResponse,
    ReasonCode,
    StatusHistoryEntry,
    Urgency,
)
from app.models.user import DoctorVerificationStatus, UserInDB, UserRole
from app.services.case_service import CaseService, compute_age_band, compute_waiting_time_seconds
from app.services.patient_service import PatientService
from app.services.state_machine import transition

router = APIRouter(prefix="/cases", tags=["Cases"])


@router.post("", response_model=CaseStatusResponse, status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseCreateRequest,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
) -> CaseStatusResponse:
    """
    Creates a new screening case draft in 'draft' status.
    - Patient: Creates draft for self (patient_id deduced from own user record).
    - Screener: Creates draft for in-person screener-created patient profile.
    - Doctor, Coordinator, Admin: 403 Forbidden.
    """
    # Gate 1: Role check
    if current_user.role not in (UserRole.PATIENT, UserRole.SCREENER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role}' is not authorized to create screening cases.",
        )

    if current_user.role == UserRole.PATIENT:
        # Patient self-screening: resolve linked patient profile
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient profile not found for authenticated user.",
            )
        target_patient_id = str(patient["_id"])

    else:
        # Screener camp screening: requires valid patient_id created by this screener
        if not payload.patient_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="patient_id is required when creating cases as a screener.",
            )
        patient = await patient_service.get_patient_by_id(payload.patient_id)
        # Anti-probing: if not found or created by another screener -> 404
        if not patient or str(patient.get("created_by")) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient record not found.",
            )
        target_patient_id = str(patient["_id"])

    new_case = await case_service.create_case_draft(
        patient_id=target_patient_id,
        created_by=current_user.id,
        is_demo=current_user.is_demo,
    )

    return CaseStatusResponse(
        id=str(new_case.id),
        reference=new_case.reference,
        status=new_case.status,
        patient_id=new_case.patient_id,
        created_at=new_case.created_at,
        updated_at=new_case.updated_at,
    )


@router.get("", response_model=list[CaseStatusResponse])
async def list_cases(
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
) -> list[CaseStatusResponse]:
    """
    Lists past cases accessible to the authenticated caller.
    - Patient: Returns cases belonging to own profile.
    - Screener: Returns cases created by this screener.
    - Doctor, Coordinator, Admin: 403 Forbidden.
    """
    # Gate 1: Role check
    if current_user.role not in (UserRole.PATIENT, UserRole.SCREENER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role}' cannot list cases via this endpoint.",
        )

    if current_user.role == UserRole.PATIENT:
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient:
            return []
        raw_cases = await case_service.get_cases_for_patient(str(patient["_id"]))
    else:
        raw_cases = await case_service.get_cases_created_by(current_user.id)

    return [
        CaseStatusResponse(
            id=str(c.get("id") or c.get("_id")),
            reference=c["reference"],
            status=CaseStatus(c["status"]),
            patient_id=c["patient_id"],
            created_at=c["created_at"],
            updated_at=c["updated_at"],
        )
        for c in raw_cases
    ]


@router.get("/{id}")
async def get_case(
    id: str,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
) -> Any:
    """
    Role-scoped case viewer applying PERMISSIONS.md Section 1 gates:
    - Gate 1: Wrong role -> 403 Forbidden (Admins and Coordinators).
    - Gate 2: Unverified doctor -> 403 Forbidden uniformly.
    - Gate 3: Ownership check -> 404 Not Found (Anti-probing).
    Payload varies strictly by role:
    - Patient / Screener: CaseStatusResponse (status only).
    - Verified Doctor on Pool Case (queued/ai_analyzed, unassigned): CasePoolMetadataResponse (metadata only).
    - Assigned / Second-Opinion Doctor: CaseDetailResponse (full clinical view).
    """
    # Gate 1: Role check (Admins and Coordinators never access this endpoint directly)
    if current_user.role in (UserRole.ADMIN, UserRole.HOSPITAL_COORDINATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: clinical inspection is restricted to authorized clinicians and patient owners.",
        )

    # Gate 2: Clinical verification check
    if current_user.role == UserRole.DOCTOR and current_user.verification_status != DoctorVerificationStatus.VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor account is unverified. Clinical access forbidden.",
        )

    # Fetch case document
    case = await case_service.get_case_by_id(id)
    if not case:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found",
        )

    case_id_str = str(case["_id"])

    # Gate 3: Ownership & Scoped Projections
    if current_user.role == UserRole.PATIENT:
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient or case.get("patient_id") != str(patient["_id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

        return CaseStatusResponse(
            id=case_id_str,
            reference=case["reference"],
            status=CaseStatus(case["status"]),
            patient_id=case["patient_id"],
            created_at=case["created_at"],
            updated_at=case["updated_at"],
        )

    if current_user.role == UserRole.SCREENER:
        if case.get("created_by") != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

        return CaseStatusResponse(
            id=case_id_str,
            reference=case["reference"],
            status=CaseStatus(case["status"]),
            patient_id=case["patient_id"],
            created_at=case["created_at"],
            updated_at=case["updated_at"],
        )

    # Doctor branch
    assigned_doc_id = case.get("assigned_doctor_id")
    second_op_doc_id = case.get("second_opinion_doctor_id")
    case_status = CaseStatus(case["status"])

    # Assigned or Second-Opinion Doctor: Full clinical view
    if assigned_doc_id == current_user.id or second_op_doc_id == current_user.id:
        return CaseDetailResponse(
            id=case_id_str,
            reference=case["reference"],
            patient_id=case["patient_id"],
            created_by=case["created_by"],
            status=case_status,
            urgency=Urgency(case["urgency"]) if case.get("urgency") else None,
            assigned_doctor_id=assigned_doc_id,
            second_opinion_doctor_id=second_op_doc_id,
            version=case.get("version", 1),
            anatomical_sites=case.get("anatomical_sites", []),
            is_demo=case.get("is_demo", False),
            created_at=case["created_at"],
            updated_at=case["updated_at"],
        )

    # Verified Doctor viewing Unassigned Pool Case: Metadata only (ai_analyzed with no assigned clinician)
    if assigned_doc_id is None and case_status == CaseStatus.AI_ANALYZED:
        # Look up patient profile to compute age band
        patient_doc = await patient_service.get_patient_by_id(case["patient_id"])
        age_band = compute_age_band(patient_doc.get("date_of_birth") if patient_doc else None)
        wait_seconds = compute_waiting_time_seconds(case["created_at"])

        return CasePoolMetadataResponse(
            id=case_id_str,
            reference=case["reference"],
            status=case_status,
            age_band=age_band,
            urgency=Urgency(case["urgency"]) if case.get("urgency") else None,
            waiting_time_seconds=wait_seconds,
            anatomical_sites=case.get("anatomical_sites", []),
        )

    # Doctor looking at someone else's assigned case: 404 (Anti-probing)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")


@router.post("/{id}/cancel", response_model=CaseStatusResponse)
async def cancel_case(
    id: str,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
    payload: CaseCancelRequest | None = None,
) -> CaseStatusResponse:
    """
    Cancels a screening case prior to signing.
    - Patient (Owner) or Screener (Creator) only.
    - Doctors, Coordinators, and Admins: 403 Forbidden.
    - Cases at or after 'signed': 409 Conflict.
    - Other non-owners: 404 Not Found.
    """
    # Gate 1: Role check
    if current_user.role not in (UserRole.PATIENT, UserRole.SCREENER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role}' is not authorized to cancel screening cases.",
        )

    # Fetch case document
    case = await case_service.get_case_by_id(id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    # Gate 3: Ownership check
    if current_user.role == UserRole.PATIENT:
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient or case.get("patient_id") != str(patient["_id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
        reason_code = ReasonCode.PATIENT_CANCELLED
    else:
        if case.get("created_by") != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
        reason_code = ReasonCode.SCREENER_CANCELLED

    reason_txt = payload.reason_text if payload else None

    # Execute transition via the authoritative state machine service
    updated_case = await transition(
        case_id=case["_id"],
        to_state=CaseStatus.CANCELLED,
        actor=current_user,
        reason_code=reason_code,
        reason_text=reason_txt,
    )

    return CaseStatusResponse(
        id=str(updated_case["_id"]),
        reference=updated_case["reference"],
        status=CaseStatus(updated_case["status"]),
        patient_id=updated_case["patient_id"],
        created_at=updated_case["created_at"],
        updated_at=updated_case["updated_at"],
    )


@router.get("/{id}/timeline", response_model=CaseTimelineResponse)
async def get_case_timeline(
    id: str,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
) -> CaseTimelineResponse:
    """
    Retrieves status transition timeline for a case.
    Restricted strictly to verified assigned or second-opinion clinicians.
    All other roles or unverified doctors receive 403; non-assigned clinicians receive 404.
    """
    # Gate 1: Role check
    if current_user.role != UserRole.DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: clinical status timeline is restricted to reviewing medical practitioners.",
        )

    # Gate 2: Verification check
    if current_user.verification_status != DoctorVerificationStatus.VERIFIED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor account is unverified.",
        )

    case = await case_service.get_case_by_id(id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    # Gate 3: Ownership check (assigned doctor or second opinion doctor only)
    if case.get("assigned_doctor_id") != current_user.id and case.get("second_opinion_doctor_id") != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    timeline = [
        StatusHistoryEntry(
            from_status=h["from_status"],
            to_status=h["to_status"],
            actor_id=h["actor_id"],
            actor_role=h["actor_role"],
            timestamp=h["timestamp"],
            reason_code=h["reason_code"],
            reason_text=h.get("reason_text"),
        )
        for h in case.get("status_history", [])
    ]

    return CaseTimelineResponse(
        case_id=str(case["_id"]),
        reference=case["reference"],
        timeline=timeline,
    )
