from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_consent_service,
    get_current_user,
    get_patient_service,
)
from app.models.consent import ConsentRecord, ConsentResponse, ConsentSubmitRequest
from app.models.user import UserInDB, UserRole
from app.services.consent_service import ConsentService
from app.services.patient_service import PatientService

router = APIRouter(prefix="/consent", tags=["Consent"])


@router.get("/current", response_model=ConsentResponse)
def get_current_consent(
    consent_service: Annotated[ConsentService, Depends(get_consent_service)],
) -> ConsentResponse:
    """
    Returns the current active informed consent text, version, and SHA-256 hash.
    Publicly accessible so prospective volunteers and screeners can read prior to registration.
    """
    return consent_service.get_current_consent()


@router.post("", response_model=ConsentRecord, status_code=status.HTTP_201_CREATED)
async def submit_consent(
    payload: ConsentSubmitRequest,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    consent_service: Annotated[ConsentService, Depends(get_consent_service)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
) -> ConsentRecord:
    """
    Records an immutable participant informed consent agreement.
    - Patient: Signs for own profile (captured_by = 'self').
    - Screener: Captures in-person consent for a screener-created profile (captured_by = screener.id).
    - Other roles: 403 Forbidden.
    - Wrong ownership: 404 Not Found (Anti-probing invariant).
    """
    # Gate 1: Role check
    if current_user.role not in (UserRole.PATIENT, UserRole.SCREENER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{current_user.role}' is not authorized to record informed consent.",
        )

    if not payload.consent_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informed consent must be explicitly accepted.",
        )

    # Gate 3: Ownership check
    patient = await patient_service.get_patient_by_id(payload.patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found.",
        )

    if current_user.role == UserRole.PATIENT:
        if str(patient.get("user_id")) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient profile not found.",
            )
        captured_by = "self"
        user_id_ref = current_user.id
    else:
        # Screener
        if str(patient.get("created_by")) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Patient profile not found.",
            )
        captured_by = str(current_user.id)
        user_id_ref = patient.get("user_id")

    try:
        consent_record = await consent_service.record_consent(
            user_id=user_id_ref,
            patient_id=str(patient["_id"]),
            version=payload.consent_version,
            language=payload.language,
            captured_by=captured_by,
        )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    return consent_record
