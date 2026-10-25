from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class AnatomicalSite(str, Enum):
    """
    Seven standardized oral cavity sites per docs/DECISIONS.md Decision 1.
    """

    LEFT_CHEEK = "left_cheek"
    RIGHT_CHEEK = "right_cheek"
    TONGUE_TOP = "tongue_top"
    TONGUE_SIDES = "tongue_sides"
    FLOOR_OF_MOUTH = "floor_of_mouth"
    HARD_PALATE = "hard_palate"
    LIPS_AND_GUMS = "lips_and_gums"


class ViewType(str, Enum):
    """Oral photograph view type per SPEC 5.3."""

    LESION_CLOSEUP = "lesion_closeup"
    CONTEXT = "context"


class QualityStatus(str, Enum):
    """Image quality evaluation status."""

    PASSED = "passed"
    REJECTED = "rejected"


class ImageUploadResponse(BaseModel):
    """Advisory response returned immediately upon image upload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    site: AnatomicalSite
    view_type: ViewType
    quality_status: QualityStatus
    reason_codes: list[str]
    quality_scores: dict[str, Any]
    created_at: datetime


class ImageSummaryResponse(BaseModel):
    """Public/clinical metadata for uploaded oral photographs (no AI data)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    site: AnatomicalSite
    view_type: ViewType
    quality_status: QualityStatus
    reason_codes: list[str]
    created_at: datetime | None = None


class ImageInDB(BaseModel):
    """Image record representation stored in the images collection."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    case_id: str
    site: str
    view_type: str
    storage_id: str
    quality_scores: dict[str, Any]
    quality_status: str
    reason_codes: list[str]
    sha256: str
    created_at: datetime
    updated_at: datetime
