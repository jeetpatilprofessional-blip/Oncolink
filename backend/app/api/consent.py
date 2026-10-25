from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_consent_service
from app.models.consent import ConsentResponse
from app.services.consent_service import ConsentService

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
