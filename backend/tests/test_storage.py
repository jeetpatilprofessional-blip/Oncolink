import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.storage import GridFSStorageService


@pytest.mark.asyncio
async def test_gridfs_save_open_delete_round_trip(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
) -> None:
    """
    Test full round-trip for GridFSStorageService:
    1. Save image bytes with filename, content_type, and metadata.
    2. Verify file exists.
    3. Open file and verify exact byte content, filename, and metadata match.
    4. Delete file and verify exists returns False.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    storage = GridFSStorageService(db, bucket_name="test_case_images")

    test_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb"
    test_filename = "lesion_tongue_lateral.jpg"
    test_metadata = {"site": "tongue_sides", "screener_ref": "SCR-104", "quality_score": 0.95}

    # 1. Save
    file_id = await storage.save(
        filename=test_filename,
        data=test_image_bytes,
        content_type="image/jpeg",
        metadata=test_metadata,
    )
    assert isinstance(file_id, str)
    assert len(file_id) > 0

    # 2. Exists
    assert await storage.exists(file_id) is True

    # 3. Open and verify contents
    data, filename, metadata = await storage.open(file_id)
    assert data == test_image_bytes
    assert filename == test_filename
    assert metadata["site"] == "tongue_sides"
    assert metadata["screener_ref"] == "SCR-104"
    assert metadata["contentType"] == "image/jpeg"

    # 4. Delete
    deleted = await storage.delete(file_id)
    assert deleted is True

    # 5. Verify no longer exists
    assert await storage.exists(file_id) is False


@pytest.mark.asyncio
async def test_gridfs_deleted_file_cannot_be_opened(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
) -> None:
    """
    Prove that once a file is deleted from GridFS, attempting to open it
    raises FileNotFoundError and subsequent deletes return False.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    storage = GridFSStorageService(db, bucket_name="test_case_images")

    file_id = await storage.save(
        filename="temp_lesion.jpg",
        data=b"temp_data_bytes",
        content_type="image/jpeg",
    )

    # Confirm it can be opened initially
    content, _, _ = await storage.open(file_id)
    assert content == b"temp_data_bytes"

    # Delete the file
    assert await storage.delete(file_id) is True

    # Attempting to open a deleted file MUST raise FileNotFoundError
    with pytest.raises(FileNotFoundError, match="not found in GridFS"):
        await storage.open(file_id)

    # Deleting an already deleted file returns False
    assert await storage.delete(file_id) is False
