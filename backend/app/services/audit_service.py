from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClientSession, AsyncIOMotorDatabase

from app.models.audit import AuditEventType, AuditLogEntry

FORBIDDEN_SECRET_SUBSTRINGS = (
    "password",
    "token",
    "secret",
    "recovery_code",
)


def is_forbidden_key(key: str) -> bool:
    """Returns True if key name indicates sensitive credential data."""
    kl = key.lower()
    return any(term in kl for term in FORBIDDEN_SECRET_SUBSTRINGS)


def sanitize_audit_details(details: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively strips any secret fields (passwords, tokens, TOTP secrets)
    from details dictionaries before persisting to the append-only audit log.
    """
    clean: dict[str, Any] = {}
    for k, v in details.items():
        if is_forbidden_key(k):
            continue
        if isinstance(v, dict):
            clean[k] = sanitize_audit_details(v)
        elif isinstance(v, list):
            clean[k] = [
                sanitize_audit_details(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            clean[k] = v
    return clean


class AuditService:
    """
    Append-only audit logging service backed by the 'audit_log' collection.

    CRITICAL ARCHITECTURAL GUARANTEE:
    This service exposes strictly insert and read methods. It purposefully does not
    contain or expose any update or delete methods, ensuring an immutable clinical audit trail.
    """

    def __init__(self, db: AsyncIOMotorDatabase):
        self._db = db
        self._collection = db["audit_log"]

    async def insert(
        self,
        event_type: AuditEventType | str,
        actor_id: str | None = None,
        actor_role: str | None = None,
        target_user_id: str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        session: AsyncIOMotorClientSession | None = None,
    ) -> str:
        """
        Appends an immutable audit log entry.
        Never stores passwords, tokens, or TOTP secrets.
        """
        clean_details = sanitize_audit_details(details or {})
        raw_event_type = event_type.value if hasattr(event_type, "value") else str(event_type)

        entry_doc = {
            "timestamp": datetime.now(UTC),
            "event_type": raw_event_type,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "target_user_id": target_user_id,
            "details": clean_details,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }
        result = await self._collection.insert_one(entry_doc, session=session)
        return str(result.inserted_id)

    async def get_logs(
        self,
        limit: int = 100,
        skip: int = 0,
        event_type: str | None = None,
    ) -> list[AuditLogEntry]:
        """Reads audit log entries ordered chronologically descending."""
        query: dict[str, Any] = {}
        if event_type:
            query["event_type"] = event_type

        cursor = self._collection.find(query).sort("timestamp", -1).skip(skip).limit(limit)
        logs = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            logs.append(AuditLogEntry(**doc))
        return logs

    async def get_by_user(self, user_id: str, limit: int = 50) -> list[AuditLogEntry]:
        """Reads audit log entries where target_user_id or actor_id matches user_id."""
        query = {"$or": [{"actor_id": user_id}, {"target_user_id": user_id}]}
        cursor = self._collection.find(query).sort("timestamp", -1).limit(limit)
        logs = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            logs.append(AuditLogEntry(**doc))
        return logs
