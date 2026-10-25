from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import pymongo
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorClientSession, AsyncIOMotorDatabase

from app.config import Settings, get_settings
from app.logging import logger

T = TypeVar("T")

# Global client reference
_client: AsyncIOMotorClient | None = None
_current_db_name: str | None = None


def create_mongo_client(settings: Settings | None = None) -> AsyncIOMotorClient:
    """Create a new AsyncIOMotorClient instance."""
    cfg = settings or get_settings()
    return AsyncIOMotorClient(
        cfg.mongo_uri,
        serverSelectionTimeoutMS=4000,
        connectTimeoutMS=4000,
    )


def get_client() -> AsyncIOMotorClient:
    """Get the active MongoDB client. Raises RuntimeError if not initialized."""
    global _client
    if _client is None:
        raise RuntimeError("MongoDB client is not initialized. Call init_db first.")
    return _client


def get_db(db_name: str | None = None) -> AsyncIOMotorDatabase:
    """Get the database instance."""
    client = get_client()
    name = db_name or _current_db_name or get_settings().mongo_db_name
    return client[name]


def get_database(db_name: str | None = None) -> AsyncIOMotorDatabase:
    """Alias for get_db."""
    return get_db(db_name)


async def init_indexes(db: AsyncIOMotorDatabase) -> None:
    """Ensure core database indexes and unique constraints are established."""
    try:
        # Users email uniqueness
        await db["users"].create_index("email", unique=True)
        # Refresh tokens hash uniqueness & lookups
        await db["refresh_tokens"].create_index("token_hash", unique=True)
        await db["refresh_tokens"].create_index("family_id")
        await db["refresh_tokens"].create_index("user_id")
        # Audit log index
        await db["audit_log"].create_index([("timestamp", pymongo.DESCENDING)])
        await db["audit_log"].create_index("event_type")
        await db["audit_log"].create_index("actor_id")
        # Consents index
        await db["consents"].create_index("user_id")
        logger.info("Database indexes initialized successfully")
    except Exception as exc:
        logger.warning("Index initialization notice", extra={"error": str(exc)})


async def init_db(settings: Settings | None = None) -> AsyncIOMotorClient:
    """
    Initialize MongoDB client and verify connectivity.
    Refuses to start if MongoDB is unreachable (per specification rule).
    """
    global _client, _current_db_name
    cfg = settings or get_settings()
    _current_db_name = cfg.mongo_db_name
    client = create_mongo_client(cfg)
    try:
        # Ping the admin database to verify connectivity and replica set reachability
        await client.admin.command("ping")
        logger.info("Connected to MongoDB successfully", extra={"db": cfg.mongo_db_name})
        db = client[cfg.mongo_db_name]
        await init_indexes(db)
    except Exception as exc:
        logger.critical(
            "Failed to connect to MongoDB. Refusing to start.",
            extra={"error": str(exc)},
        )
        raise RuntimeError(f"MongoDB is unreachable at {cfg.mongo_uri}: {exc}") from exc

    _client = client
    return _client


async def close_db() -> None:
    """Close the active MongoDB client."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("Closed MongoDB connection")


async def check_mongodb_health(client: AsyncIOMotorClient | None = None) -> dict[str, Any]:
    """Check MongoDB status and return diagnostic health information."""
    target_client = client or _client
    if target_client is None:
        return {"status": "disconnected", "error": "Client not initialized"}

    try:
        ping_res = await target_client.admin.command("ping")
        is_ok = ping_res.get("ok") == 1
        rs_name = None
        try:
            hello = await target_client.admin.command("hello")
            rs_name = hello.get("setName")
        except Exception:
            pass

        return {
            "status": "connected" if is_ok else "unhealthy",
            "replica_set": rs_name,
        }
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}


async def run_transaction(
    client: AsyncIOMotorClient,
    callback: Callable[[AsyncIOMotorClientSession], Awaitable[T]],
) -> T:
    """
    Execute an atomic multi-document transaction across one or more collections.
    If the callback raises an exception, the transaction is automatically aborted
    and all writes rolled back. If successful, the transaction is committed.
    """
    async with await client.start_session() as session:
        async with session.start_transaction():
            return await callback(session)
