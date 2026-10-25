from datetime import UTC, date, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.models.case import CaseInDB, CaseStatus, ReasonCode, generate_case_reference


def compute_age_band(dob_str: str | None) -> str:
    """Computes clinical age band from ISO date string."""
    if not dob_str:
        return "unknown"
    try:
        dob = datetime.strptime(dob_str.strip(), "%Y-%m-%d").date()
        today = date.today()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age < 30:
            return "18-29"
        if age <= 65:
            return "30-65"
        return "65+"
    except Exception:
        return "unknown"


def compute_waiting_time_seconds(created_at: datetime) -> int:
    """Computes elapsed wait time in seconds."""
    now = datetime.now(UTC)
    c_time = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    return max(0, int((now - c_time).total_seconds()))


class CaseService:
    """Manages case lifecycle draft initialization and query retrieval."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self._db = db
        self._collection = db["cases"]

    async def create_case_draft(
        self,
        patient_id: str,
        created_by: str,
        is_demo: bool = False,
        session: AsyncIOMotorClientSession | None = None,
    ) -> CaseInDB:
        """
        Creates a new screening case draft in 'draft' status.
        Guarantees random, non-sequential reference code generation with collision retry.
        """
        now = datetime.now(UTC)

        for _ in range(5):
            ref = generate_case_reference()
            doc = {
                "patient_id": str(patient_id),
                "created_by": str(created_by),
                "status": CaseStatus.DRAFT.value,
                "urgency": None,
                "assigned_doctor_id": None,
                "second_opinion_doctor_id": None,
                "reference": ref,
                "status_history": [
                    {
                        "from_status": "none",
                        "to_status": CaseStatus.DRAFT.value,
                        "actor_id": str(created_by),
                        "actor_role": "creator",
                        "timestamp": now,
                        "reason_code": ReasonCode.DRAFT_CREATED.value,
                        "reason_text": None,
                    }
                ],
                "version": 1,
                "anatomical_sites": [],
                "is_demo": is_demo,
                "created_at": now,
                "updated_at": now,
            }
            try:
                res = await self._collection.insert_one(doc, session=session)
                doc["id"] = str(res.inserted_id)
                return CaseInDB(**doc)
            except DuplicateKeyError:
                continue

        raise RuntimeError("Failed to generate unique case reference after multiple attempts.")

    async def get_case_by_id(
        self,
        case_id: str | ObjectId,
        session: AsyncIOMotorClientSession | None = None,
    ) -> dict[str, Any] | None:
        """Retrieves raw case document by ID."""
        oid = ObjectId(case_id) if ObjectId.is_valid(str(case_id)) else case_id
        return await self._collection.find_one({"_id": oid}, session=session)

    async def get_cases_for_patient(
        self,
        patient_id: str,
        session: AsyncIOMotorClientSession | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieves past cases belonging to a specific patient profile."""
        cursor = self._collection.find({"patient_id": str(patient_id)}, session=session).sort("created_at", -1)
        results = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            results.append(doc)
        return results

    async def get_cases_created_by(
        self,
        creator_id: str,
        session: AsyncIOMotorClientSession | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieves screening cases created by a specific user (screener)."""
        cursor = self._collection.find({"created_by": str(creator_id)}, session=session).sort("created_at", -1)
        results = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            results.append(doc)
        return results
