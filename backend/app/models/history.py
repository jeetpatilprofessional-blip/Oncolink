from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Frequency(str, Enum):
    """Standardized consumption frequency enum."""

    NEVER = "never"
    OCCASIONAL = "occasional"
    DAILY = "daily"


class CaseHistoryPayload(BaseModel):
    """
    Structured patient oral health and exposure history questionnaire.
    Strictly forbids free-text and unknown fields (ConfigDict(extra="forbid")).
    """

    model_config = ConfigDict(extra="forbid")

    # Tobacco exposure (SPEC 5.2)
    tobacco_smoked_frequency: Frequency
    tobacco_smoked_years: int = Field(ge=0, le=100)
    tobacco_smokeless_frequency: Frequency
    tobacco_smokeless_years: int = Field(ge=0, le=100)
    areca_nut_frequency: Frequency
    areca_nut_years: int = Field(ge=0, le=100)
    betel_quid_frequency: Frequency
    betel_quid_years: int = Field(ge=0, le=100)

    # Alcohol exposure
    alcohol_frequency: Frequency

    # Lesion characteristics
    lesion_duration_weeks: int = Field(ge=0, le=520)
    lesion_pain: bool
    lesion_non_healing_two_weeks: bool
    lesion_bleeding: bool
    lesion_white_or_red_patch: bool
    lesion_lump: bool

    # Functional impairment
    difficulty_swallowing: bool
    difficulty_opening_mouth: bool
    difficulty_speaking: bool
    unexplained_weight_loss: bool

    # Family history
    family_history_cancer: bool

    # Red-flag symptoms (SPEC 5.2 & 5.5)
    heavy_bleeding: bool
    difficulty_breathing: bool
    rapid_swelling: bool


class CaseHistoryInDB(BaseModel):
    """Database representation stored in case_history collection."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    case_id: str
    history: dict[str, Any]
    created_at: datetime
    updated_at: datetime
