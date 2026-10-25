from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.validators import AdultDateOfBirth


class PatientCreateRequest(BaseModel):
    date_of_birth: AdultDateOfBirth
    language: str = Field(default="en", min_length=2, max_length=10)
    contact: str | None = None


class PatientResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None = None
    created_by: str
    date_of_birth: str
    language: str = "en"
    contact: str | None = None
    erased: bool = False
    is_demo: bool = False
    created_at: datetime


class PatientInDB(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    user_id: str | None = None
    created_by: str
    date_of_birth: str
    language: str = "en"
    contact: str | None = None
    erased: bool = False
    is_demo: bool = False
    created_at: datetime
    updated_at: datetime
