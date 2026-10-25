from abc import ABC, abstractmethod
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from gridfs.errors import NoFile
from motor.motor_asyncio import AsyncIOMotorDatabase, AsyncIOMotorGridFSBucket

from app.config import Settings, get_settings
from app.database import get_db
from app.logging import logger


class StorageService(ABC):
    """
    Abstract storage interface for medical and clinical images.
    Enables swapping the underlying storage implementation (GridFS, S3/Cloud Storage)
    without altering domain or API code. Images are strictly private and served only
    via authenticated backend endpoints.
    """

    @abstractmethod
    async def save(
        self,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store image bytes and return unique string file_id."""
        pass

    @abstractmethod
    async def open(self, file_id: str) -> tuple[bytes, str, dict[str, Any]]:
        """
        Retrieve stored image bytes, filename, and metadata by file_id.
        Raises FileNotFoundError if the file does not exist or has been deleted.
        """
        pass

    @abstractmethod
    async def delete(self, file_id: str) -> bool:
        """Delete stored image by file_id. Returns True if deleted, False if not found."""
        pass

    @abstractmethod
    async def exists(self, file_id: str) -> bool:
        """Check if image exists by file_id."""
        pass


class GridFSStorageService(StorageService):
    """
    MongoDB GridFS storage implementation.
    Stores clinical images directly inside MongoDB chunks/files collections.
    """

    def __init__(self, db: AsyncIOMotorDatabase, bucket_name: str = "case_images") -> None:
        self.db = db
        self.bucket_name = bucket_name
        self.bucket = AsyncIOMotorGridFSBucket(db, bucket_name=bucket_name)

    async def save(
        self,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        meta = metadata or {}
        meta["contentType"] = content_type

        file_id = await self.bucket.upload_from_stream(
            filename=filename,
            source=data,
            metadata=meta,
        )
        return str(file_id)

    async def open(self, file_id: str) -> tuple[bytes, str, dict[str, Any]]:
        try:
            oid = ObjectId(file_id)
        except InvalidId as exc:
            raise FileNotFoundError(f"Invalid file id format: {file_id}") from exc

        try:
            grid_out = await self.bucket.open_download_stream(oid)
            content = await grid_out.read()
            filename = grid_out.filename or "image"
            metadata = grid_out.metadata or {}
            return content, filename, metadata
        except NoFile as exc:
            raise FileNotFoundError(f"File with id {file_id} not found in GridFS") from exc

    async def delete(self, file_id: str) -> bool:
        try:
            oid = ObjectId(file_id)
        except InvalidId:
            return False

        if not await self.exists(file_id):
            return False

        try:
            await self.bucket.delete(oid)
            return True
        except (NoFile, InvalidId):
            return False

    async def exists(self, file_id: str) -> bool:
        try:
            oid = ObjectId(file_id)
        except InvalidId:
            return False

        files_col = self.db[f"{self.bucket_name}.files"]
        doc = await files_col.find_one({"_id": oid})
        return doc is not None


_storage_service: StorageService | None = None


def get_storage(settings: Settings | None = None) -> StorageService:
    """Get or initialize the global StorageService."""
    global _storage_service
    if _storage_service is None:
        cfg = settings or get_settings()
        db = get_db()
        _storage_service = GridFSStorageService(db, bucket_name=cfg.gridfs_bucket_name)
    return _storage_service


async def check_gridfs_health(
    db: AsyncIOMotorDatabase | None = None,
    bucket_name: str | None = None,
) -> dict[str, Any]:
    """Check GridFS availability and bucket status."""
    try:
        target_db = db or get_db()
        b_name = bucket_name or get_settings().gridfs_bucket_name
        # Test collection access
        files_col = target_db[f"{b_name}.files"]
        count = await files_col.count_documents({})
        return {
            "status": "connected",
            "bucket": b_name,
            "file_count": count,
        }
    except Exception as exc:
        logger.error("GridFS health check failed", extra={"error": str(exc)})
        return {
            "status": "unhealthy",
            "error": str(exc),
        }
