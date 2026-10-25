from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

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
        user_id: str,
        version: str,
        language: str = CONSENT_LANGUAGE,
        captured_by: str = "self",
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

        record_doc = {
            "user_id": str(user_id),
            "version": version,
            "language": language,
            "text_hash": get_consent_text_hash(),
            "accepted_at": datetime.now(UTC),
            "captured_by": captured_by,
        }
        result = await self._collection.insert_one(record_doc)
        record_doc["id"] = str(result.inserted_id)
        return ConsentRecord(**record_doc)

    async def get_consent_for_user(self, user_id: str) -> ConsentRecord | None:
        """Retrieves consent record for a given user."""
        doc = await self._collection.find_one({"user_id": str(user_id)})
        if not doc:
            return None
        doc["id"] = str(doc.pop("_id"))
        return ConsentRecord(**doc)
