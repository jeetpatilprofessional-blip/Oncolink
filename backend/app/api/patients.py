from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, get_patient_service
from app.models.patient import PatientCreateRequest, PatientResponse
from app.models.user import UserInDB, UserRole
from app.models.validators import calculate_age
from app.services.patient_service import PatientService

router = APIRouter(prefix="/patients", tags=["Patients"])


@router.post("", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
async def create_patient_profile(
    payload: PatientCreateRequest,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
    patient_service: Annotated[PatientService, Depends(get_patient_service)],
) -> PatientResponse:
    """
    Field screener creates an unauthenticated patient profile for camp/clinic screening.
    Restricted strictly to the 'screener' role.
    Rejects any individual under 18 years of age.
    """
    # Gate 1: Role check (screener only)
    if current_user.role != UserRole.SCREENER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access forbidden: role '{current_user.role}' cannot create patient profiles directly.",
        )

    # Validate age >= 18
    try:
        age = calculate_age(payload.date_of_birth)
        if age < 18:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient must be an adult aged 18 or older.",
            )
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err

    new_patient = await patient_service.create_patient(
        created_by=current_user.id,
        date_of_birth=payload.date_of_birth,
        user_id=None,
        language=payload.language,
        contact=payload.contact,
        is_demo=current_user.is_demo,
    )

    return PatientResponse(
        id=str(new_patient.id),
        user_id=None,
        created_by=str(new_patient.created_by),
        date_of_birth=new_patient.date_of_birth,
        language=new_patient.language,
        contact=new_patient.contact,
        erased=new_patient.erased,
        is_demo=new_patient.is_demo,
        created_at=new_patient.created_at,
    )
