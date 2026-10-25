from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClientSession, AsyncIOMotorDatabase

from app.models.patient import PatientInDB
from app.models.validators import validate_adult_dob


class PatientService:
    """Manages participant and community patient profiles."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self._db = db
        self._collection = db["patients"]

    async def create_patient(
        self,
        created_by: str,
        date_of_birth: str,
        user_id: str | None = None,
        language: str = "en",
        contact: str | None = None,
        is_demo: bool = False,
        session: AsyncIOMotorClientSession | None = None,
    ) -> PatientInDB:
        """
        Creates a new patient profile.
        Strictly enforces that patient is an adult aged 18 or older.
        """
        valid_dob = validate_adult_dob(date_of_birth)
        now = datetime.now(UTC)

        doc = {
            "user_id": str(user_id) if user_id else None,
            "created_by": str(created_by),
            "date_of_birth": valid_dob,
            "language": language or "en",
            "contact": contact,
            "erased": False,
            "is_demo": is_demo,
            "created_at": now,
            "updated_at": now,
        }

        res = await self._collection.insert_one(doc, session=session)
        doc["id"] = str(res.inserted_id)
        return PatientInDB(**doc)

    async def get_patient_by_id(
        self,
        patient_id: str | ObjectId,
        session: AsyncIOMotorClientSession | None = None,
    ) -> dict[str, Any] | None:
        """Fetches patient record by primary ID."""
        oid = ObjectId(patient_id) if ObjectId.is_valid(str(patient_id)) else patient_id
        return await self._collection.find_one({"_id": oid, "erased": False}, session=session)

    async def get_patient_by_user_id(
        self,
        user_id: str,
        session: AsyncIOMotorClientSession | None = None,
    ) -> dict[str, Any] | None:
        """Fetches patient profile linked to an authenticated user account."""
        return await self._collection.find_one({"user_id": str(user_id), "erased": False}, session=session)
