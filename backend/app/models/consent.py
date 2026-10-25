from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConsentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    user_id: str | None = None
    patient_id: str | None = None
    version: str
    language: str
    text_hash: str
    accepted_at: datetime
    captured_by: str = "self"


class ConsentSubmitRequest(BaseModel):
    patient_id: str
    consent_version: str
    consent_accepted: bool
    language: str = "en"


class ConsentResponse(BaseModel):
    version: str
    language: str
    text: str
    text_hash: str
