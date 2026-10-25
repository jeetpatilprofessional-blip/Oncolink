from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.deps import (
    get_audit_service,
    get_case_service,
    get_current_user,
    get_db,
    get_image_service,
    get_patient_service,
    get_storage_service,
)
from app.models.case import (
    CaseCancelRequest,
    CaseCreateRequest,
    CaseDetailResponse,
    CasePoolMetadataResponse,
    CaseStatus,
    CaseStatusResponse,
    CaseSubmitResponse,
    CaseTimelineResponse,
    FailedImageDetail,
    ReasonCode,
    StatusHistoryEntry,
    Urgency,
)
from app.models.history import CaseHistoryPayload
from app.models.image import (
    AnatomicalSite,
    ImageSummaryResponse,
    ImageUploadResponse,
    QualityStatus,
    ViewType,
)
from app.models.user import DoctorVerificationStatus, UserInDB, UserRole
from app.services.audit_service import AuditService
from app.services.case_service import CaseService, compute_age_band, compute_waiting_time_seconds
from app.services.image_service import ImageService
from app.services.patient_service import PatientService
from app.services.red_flag import evaluate_red_flags, evaluate_risk_factors
from app.services.state_machine import transition, transition_chain
from app.services.urgency import determine_urgency
from app.storage import StorageService

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
    if (
        current_user.role == UserRole.DOCTOR
        and current_user.verification_status != DoctorVerificationStatus.VERIFIED
    ):
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

    async def _load_images_summary() -> list[ImageSummaryResponse]:
        image_docs = await db["images"].find({"case_id": case_id_str}).to_list(length=50)
        return [
            ImageSummaryResponse(
                id=str(im["_id"]),
                site=AnatomicalSite(im["site"]),
                view_type=ViewType(im["view_type"]),
                quality_status=QualityStatus(im["quality_status"]),
                reason_codes=im.get("reason_codes", []),
                created_at=im.get("created_at"),
            )
            for im in image_docs
        ]

    # Gate 3: Ownership & Scoped Projections
    if current_user.role == UserRole.PATIENT:
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient or case.get("patient_id") != str(patient["_id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

        images_list = await _load_images_summary()
        return CaseStatusResponse(
            id=case_id_str,
            reference=case["reference"],
            status=CaseStatus(case["status"]),
            patient_id=case["patient_id"],
            created_at=case["created_at"],
            updated_at=case["updated_at"],
            images=images_list,
        )

    if current_user.role == UserRole.SCREENER:
        if case.get("created_by") != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

        images_list = await _load_images_summary()
        return CaseStatusResponse(
            id=case_id_str,
            reference=case["reference"],
            status=CaseStatus(case["status"]),
            patient_id=case["patient_id"],
            created_at=case["created_at"],
            updated_at=case["updated_at"],
            images=images_list,
        )

    # Doctor branch
    assigned_doc_id = case.get("assigned_doctor_id")
    second_op_doc_id = case.get("second_opinion_doctor_id")
    case_status = CaseStatus(case["status"])

    # Assigned or Second-Opinion Doctor: Full clinical view
    if assigned_doc_id == current_user.id or second_op_doc_id == current_user.id:
        images_list = await _load_images_summary()
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
            images=images_list,
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
    if (
        case.get("assigned_doctor_id") != current_user.id
        and case.get("second_opinion_doctor_id") != current_user.id
    ):
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


@router.post("/{id}/history")
async def save_case_history(
    id: str,
    payload: CaseHistoryPayload,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
) -> dict[str, Any]:
    """
    Saves or replaces the structured questionnaire history for a screening case.
    - Patient (Owner) or Screener (Creator) only.
    - Other roles: 403 Forbidden.
    - Other patients/screeners: 404 Not Found (Anti-probing).
    - Case state: draft or needs_retake only; all other states return 409 Conflict.
    - Strictly validated enums, booleans, and small integers (extra="forbid"). Zero free text.
    """
    # Gate 1: Role check
    if current_user.role not in (UserRole.PATIENT, UserRole.SCREENER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role}' is not authorized to submit case history.",
        )

    case = await case_service.get_case_by_id(id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    # Gate 2: Ownership check
    if current_user.role == UserRole.PATIENT:
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient or case.get("patient_id") != str(patient["_id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    else:
        if case.get("created_by") != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    # Gate 3: State check (draft or needs_retake only per PERMISSIONS.md Section 5)
    if case["status"] not in (CaseStatus.DRAFT.value, CaseStatus.NEEDS_RETAKE.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Case history can only be updated in 'draft' or 'needs_retake' status (current status: '{case['status']}').",
        )

    now = datetime.now(UTC)
    history_data = payload.model_dump()
    case_id_str = str(case["_id"])

    await db["case_history"].update_one(
        {"case_id": case_id_str},
        {
            "$set": {
                "case_id": case_id_str,
                "history": history_data,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        },
        upsert=True,
    )

    red_flags = evaluate_red_flags(payload)
    risk_factors = evaluate_risk_factors(payload)

    return {
        "message": "Case history recorded successfully",
        "case_id": case_id_str,
        "red_flags": red_flags,
        "risk_factors": risk_factors,
    }


@router.post("/{id}/images", response_model=ImageUploadResponse)
async def upload_case_image(
    id: str,
    file: Annotated[UploadFile, File(...)],
    site: Annotated[AnatomicalSite, Form(...)],
    view_type: Annotated[ViewType, Form(...)],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
    image_service: Annotated[ImageService, Depends(get_image_service)],
) -> ImageUploadResponse:
    """
    Uploads an oral photograph for a screening case.
    - Patient (Owner) or Screener (Creator) only.
    - Case state: draft or needs_retake only; other states return 409 Conflict.
    - Enforces magic-byte verification (JPEG, PNG, WebP), 10 MB limit, Pillow decompression bomb limit,
      re-encoding without EXIF/GPS, 12-image cap, and superseding of identical (site, view_type) photos.
    - Returns advisory quality status and reason codes immediately.
    """
    # Gate 1: Role check
    if current_user.role not in (UserRole.PATIENT, UserRole.SCREENER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role}' is not authorized to upload case photographs.",
        )

    case = await case_service.get_case_by_id(id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    # Gate 2: Ownership check
    if current_user.role == UserRole.PATIENT:
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient or case.get("patient_id") != str(patient["_id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    else:
        if case.get("created_by") != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    # Gate 3: State check
    if case["status"] not in (CaseStatus.DRAFT.value, CaseStatus.NEEDS_RETAKE.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Images can only be uploaded in 'draft' or 'needs_retake' status (current status: '{case['status']}').",
        )

    return await image_service.process_and_store_image(
        case_id=str(case["_id"]),
        site=site,
        view_type=view_type,
        file=file,
    )


@router.get("/{id}/images/{image_id}")
async def get_case_image(
    id: str,
    image_id: str,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
    image_service: Annotated[ImageService, Depends(get_image_service)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    """
    Streams an oral photograph binary strictly through authenticated, authorized access.
    - Owner Patient, Creator Screener, Assigned Doctor, Second-Opinion Doctor: 200 OK.
    - Unverified Doctor: 403 Forbidden.
    - Admin, Coordinator: 403 Forbidden.
    - Other Doctor, Pool Doctor, Other Patient, Other Screener: 404 Not Found (Anti-probing).
    - Headers: Cache-Control no-store, X-Content-Type-Options nosniff.
    - Writes immutable audit entry (IDs only). Zero public URLs.
    """
    # Gate 1: Role check
    if current_user.role in (UserRole.ADMIN, UserRole.HOSPITAL_COORDINATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: clinical photographs cannot be accessed directly by administrative or coordination staff.",
        )

    # Gate 2: Clinical verification check
    if (
        current_user.role == UserRole.DOCTOR
        and current_user.verification_status != DoctorVerificationStatus.VERIFIED
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor account is unverified. Clinical image access forbidden.",
        )

    case = await case_service.get_case_by_id(id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    case_id_str = str(case["_id"])

    # Gate 3: Ownership check
    if current_user.role == UserRole.PATIENT:
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient or case.get("patient_id") != str(patient["_id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    elif current_user.role == UserRole.SCREENER:
        if case.get("created_by") != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    elif current_user.role == UserRole.DOCTOR:
        assigned_doc_id = case.get("assigned_doctor_id")
        second_op_doc_id = case.get("second_opinion_doctor_id")
        if assigned_doc_id != current_user.id and second_op_doc_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    # Fetch image document
    image = await image_service.get_image_by_id(image_id)
    if not image or str(image.get("case_id")) != case_id_str:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    # Stream from GridFS
    try:
        data, filename, metadata = await storage_service.open(image["storage_id"])
    except FileNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image file not found in storage"
        ) from err

    # Write immutable audit entry (IDs ONLY)
    await audit_service.insert(
        event_type="image_view",
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        target_user_id=str(case.get("patient_id", "")),
        details={
            "case_id": case_id_str,
            "image_id": image_id,
            "storage_id": str(image["storage_id"]),
        },
    )

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{id}/submit", response_model=CaseSubmitResponse)
async def submit_case(
    id: str,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    case_service: Annotated[CaseService, Depends(get_case_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
) -> CaseSubmitResponse:
    """
    Submits a completed screening case for quality assessment and clinical review triage.
    - Patient (Owner) or Screener (Creator) only.
    - Case state: draft or needs_retake only. Other states return 409 Conflict.
    - Preconditions (each returning 422 with specific missing items):
      1. Active informed consent for patient (captured_by matches screener for camp screenings).
      2. Saved questionnaire history in case_history.
      3. Images covering at least one lesion_closeup and two context views.
    - State Machine Transitions executed in ONE transaction:
      1. submitted
      2. quality_check
      3. And then:
         - red_flag (if red-flag symptoms present; urgency=urgent)
         - needs_retake (if any required photo fails quality check; reason=photo_quality_failed)
         - queued (if all photos pass; reason=photo_quality_passed; urgency=routine)
    """
    # Gate 1: Role check
    if current_user.role not in (UserRole.PATIENT, UserRole.SCREENER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role}' is not authorized to submit screening cases.",
        )

    case = await case_service.get_case_by_id(id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    case_id_str = str(case["_id"])

    # Gate 2: Ownership check
    if current_user.role == UserRole.PATIENT:
        patient = await patient_service.get_patient_by_user_id(current_user.id)
        if not patient or case.get("patient_id") != str(patient["_id"]):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
        first_edge_reason = ReasonCode.SELF_SCREEN_SUBMIT
    else:
        if case.get("created_by") != current_user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
        first_edge_reason = ReasonCode.SCREENER_INTAKE_SUBMIT

    # Gate 3: State check
    if case["status"] not in (CaseStatus.DRAFT.value, CaseStatus.NEEDS_RETAKE.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Case submission is only allowed in 'draft' or 'needs_retake' status (current status: '{case['status']}').",
        )

    # 4. Check Preconditions (422 Unprocessable Entity with specific missing items)
    missing_items: list[str] = []

    # 4a. Active informed consent check
    if current_user.role == UserRole.PATIENT:
        consent = await db["consents"].find_one({"patient_id": case["patient_id"]})
    else:
        # Screener in-person consent must record captured_by == current_user.id (PERMISSIONS.md Section 1 rule 4)
        consent = await db["consents"].find_one(
            {
                "patient_id": case["patient_id"],
                "captured_by": current_user.id,
            }
        )
    if not consent:
        missing_items.append("active_consent")

    # 4b. Saved questionnaire history check
    history_doc = await db["case_history"].find_one({"case_id": case_id_str})
    if not history_doc:
        missing_items.append("case_history")

    # 4c. Photographic protocol coverage check (>= 1 lesion_closeup and >= 2 context views)
    image_docs = await db["images"].find({"case_id": case_id_str}).to_list(length=50)
    closeup_count = sum(1 for im in image_docs if im["view_type"] == ViewType.LESION_CLOSEUP.value)
    context_count = sum(1 for im in image_docs if im["view_type"] == ViewType.CONTEXT.value)

    if closeup_count < 1:
        missing_items.append("lesion_closeup_image")
    if context_count < 2:
        missing_items.append("context_images")

    if missing_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Submission preconditions not met. Please complete all required intake items.",
                "missing_items": missing_items,
            },
        )

    # 5. Authoritative Quality Gate evaluation on required protocol images
    failed_images: list[FailedImageDetail] = []
    for im in image_docs:
        if im.get("quality_status") == QualityStatus.REJECTED.value:
            failed_images.append(
                FailedImageDetail(
                    image_id=str(im["_id"]),
                    site=im["site"],
                    view_type=im["view_type"],
                    reason_codes=im.get("reason_codes", []),
                )
            )

    # 6. Red-flag and risk factor evaluation from saved questionnaire history
    history_payload = history_doc["history"]
    red_flags = evaluate_red_flags(history_payload)
    risk_factors = evaluate_risk_factors(history_payload)
    has_red_flags = len(red_flags) > 0
    assigned_urgency = determine_urgency(red_flags)

    # 7. Construct transition steps for state machine transition_chain
    caller_role_val = current_user.role.value
    steps: list[tuple[CaseStatus | str, ReasonCode | str, str | None, str]] = [
        # Edge 1: draft / needs_retake -> submitted
        (CaseStatus.SUBMITTED, first_edge_reason, None, caller_role_val),
        # Edge 2: submitted -> quality_check
        (CaseStatus.QUALITY_CHECK, ReasonCode.PHOTO_QUALITY_PASSED, None, "system"),
    ]

    # Edge 3: quality_check -> (red_flag | needs_retake | queued)
    if has_red_flags:
        # Red-flag emergency fast-tracks immediately
        steps.append((CaseStatus.RED_FLAG, ReasonCode.RED_FLAG_DETECTED, None, "system"))
    elif len(failed_images) > 0:
        # Photographic quality failed
        steps.append((CaseStatus.NEEDS_RETAKE, ReasonCode.PHOTO_QUALITY_FAILED, None, "system"))
    else:
        # Photographic quality passed -> queue for clinical triage
        steps.append((CaseStatus.QUEUED, ReasonCode.PHOTO_QUALITY_PASSED, None, "system"))

    extra_updates = {
        "urgency": assigned_urgency.value,
        "red_flags": red_flags,
        "risk_factors": risk_factors,
    }

    updated_case = await transition_chain(
        case_id=case["_id"],
        steps=steps,
        actor=current_user,
        db=db,
        extra_case_updates=extra_updates,
    )

    if has_red_flags:
        msg = "Emergency red-flag symptoms detected. Case placed at top of priority queue for immediate clinical evaluation."
    elif len(failed_images) > 0:
        msg = "Image quality check failed. Please retake the indicated photographs."
    else:
        msg = "Case successfully submitted and queued for clinical review."

    return CaseSubmitResponse(
        id=str(updated_case["_id"]),
        reference=updated_case["reference"],
        status=CaseStatus(updated_case["status"]),
        urgency=assigned_urgency,
        red_flag=has_red_flags,
        red_flag_codes=red_flags,
        risk_factors=risk_factors,
        failed_images=failed_images,
        message=msg,
    )
