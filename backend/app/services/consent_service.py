from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorClientSession, AsyncIOMotorDatabase

from app.consent_texts import (
    CONSENT_LANGUAGE,
    CONSENT_TEXT,
    CONSENT_VERSION,
    get_consent_text_hash,
)
from app.models.consent import ConsentRecord, ConsentResponse


class ConsentService:
    """Manages versioned consent text retrieval and patient consent logging."""

    def __init__(self, db: AsyncIOMotorDatabase):
        self._db = db
        self._collection = db["consents"]

    @staticmethod
    def get_current_consent() -> ConsentResponse:
        """Returns the current active informed consent text, version, and hash."""
        return ConsentResponse(
            version=CONSENT_VERSION,
            language=CONSENT_LANGUAGE,
            text=CONSENT_TEXT.strip(),
            text_hash=get_consent_text_hash(),
        )

    async def record_consent(
        self,
        user_id: str | None = None,
        patient_id: str | None = None,
        version: str = CONSENT_VERSION,
        language: str = CONSENT_LANGUAGE,
        captured_by: str = "self",
        session: AsyncIOMotorClientSession | None = None,
    ) -> ConsentRecord:
        """
        Stores an immutable record of participant informed consent.
        Verifies that the provided version matches the current active version.
        """
        current_version = CONSENT_VERSION
        if version != current_version:
            raise ValueError(
                f"Consent version '{version}' is outdated or invalid. Active version is '{current_version}'."
            )

        if not user_id and not patient_id:
            raise ValueError("Either user_id or patient_id must be provided for consent record.")

        record_doc = {
            "user_id": str(user_id) if user_id else None,
            "patient_id": str(patient_id) if patient_id else None,
            "version": version,
            "language": language,
            "text_hash": get_consent_text_hash(),
            "accepted_at": datetime.now(UTC),
            "captured_by": captured_by,
        }
        result = await self._collection.insert_one(record_doc, session=session)
        record_doc["id"] = str(result.inserted_id)
        return ConsentRecord(**record_doc)

    async def get_consent_for_user(self, user_id: str) -> ConsentRecord | None:
        """Retrieves consent record for a given user."""
        doc = await self._collection.find_one({"user_id": str(user_id)})
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return ConsentRecord(**doc)

    async def get_consent_for_patient(self, patient_id: str) -> ConsentRecord | None:
        """Retrieves consent record for a given patient."""
        doc = await self._collection.find_one({"patient_id": str(patient_id)})
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return ConsentRecord(**doc)
