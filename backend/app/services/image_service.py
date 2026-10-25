import hashlib
import io
import secrets
import warnings
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from fastapi import HTTPException, UploadFile, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from PIL import Image

from app.models.image import (
    AnatomicalSite,
    ImageUploadResponse,
    QualityStatus,
    ViewType,
)
from app.services.quality_gate import evaluate_image_quality
from app.storage import StorageService

# Maximum allowable upload payload: 10 MB
MAX_IMAGE_BYTES: int = 10 * 1024 * 1024

# Pillow Decompression Bomb Mitigation (25 megapixels maximum)
MAX_IMAGE_PIXELS: int = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

# Maximum images per screening case
MAX_IMAGES_PER_CASE: int = 12


def detect_image_format_by_magic_bytes(header: bytes) -> str:
    """
    Identifies image MIME format exclusively by inspection of file magic bytes.
    Rejects spoofed file extensions and unverified headers.
    Allowed formats: JPEG, PNG, WebP.
    """
    if len(header) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is too small to be a valid image.",
        )

    # 1. JPEG: 0xFF, 0xD8, 0xFF
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    # 2. PNG: 0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    # 3. WebP: 'RIFF' .... 'WEBP'
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid image format. Allowed formats are JPEG, PNG, and WebP (verified by magic bytes).",
    )


class ImageService:
    def __init__(self, db: AsyncIOMotorDatabase, storage: StorageService) -> None:
        self.db = db
        self.storage = storage

    async def process_and_store_image(
        self,
        case_id: str,
        site: AnatomicalSite,
        view_type: ViewType,
        file: UploadFile,
    ) -> ImageUploadResponse:
        """
        Processes and stores an uploaded clinical mouth photograph.

        Security Pipeline:
        1. Reads raw bytes and enforces <= 10 MB hard limit.
        2. Inspects magic bytes (JPEG/PNG/WebP only); rejects spoofed content-types.
        3. Enforces Pillow decompression-bomb pixel limits.
        4. Re-encodes image to strip all EXIF metadata (GPS tags, device info) and appended payloads.
        5. Enforces maximum 12 images per case.
        6. Supersedes any previous image for the same (site, view_type) and purges old GridFS chunks.
        7. Evaluates automated quality gate (advisory scores & reason codes).
        8. Stores sanitized re-encoded bytes in GridFS with metadata.
        9. Persists image record in the images collection and updates case anatomical sites.
        """
        # 1. Read raw bytes & enforce size limit
        raw_bytes = await file.read()
        if len(raw_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Image file exceeds maximum allowable size of {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
            )
        if len(raw_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty image payload received.",
            )

        # 2. Magic bytes validation & Content-Type matching
        detected_mime = detect_image_format_by_magic_bytes(raw_bytes[:16])

        # Validate provided content_type header if present
        if file.content_type:
            provided_mime = file.content_type.split(";")[0].strip().lower()
            if provided_mime not in (
                "image/jpeg",
                "image/png",
                "image/webp",
                "application/octet-stream",
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Mismatched or unsupported Content-Type: {provided_mime}",
                )
            if provided_mime != "application/octet-stream" and provided_mime != detected_mime:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Mismatched Content-Type: header '{provided_mime}' does not match detected format '{detected_mime}'.",
                )

        # 3. Decompression bomb check & decode
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw_bytes)) as pil_img:
                    if (pil_img.width * pil_img.height) > MAX_IMAGE_PIXELS:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Image resolution exceeds decompression bomb threshold (maximum 25 megapixels).",
                        )
                    # 4. Re-encode image: convert to RGB and write fresh JPEG buffer (strips all EXIF/GPS)
                    rgb_img = pil_img.convert("RGB")
                    out_buffer = io.BytesIO()
                    rgb_img.save(out_buffer, format="JPEG", quality=90, optimize=True)
                    reencoded_bytes = out_buffer.getvalue()

        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Image rejected as decompression bomb: {exc}",
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to decode image: {exc}",
            ) from exc

        # 5. Check 12-image cap and check for superseding image
        existing_images = await self.db["images"].find({"case_id": case_id}).to_list(length=20)
        superseded_img = next(
            (
                img
                for img in existing_images
                if img["site"] == site.value and img["view_type"] == view_type.value
            ),
            None,
        )

        if superseded_img is None and len(existing_images) >= MAX_IMAGES_PER_CASE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum limit of {MAX_IMAGES_PER_CASE} images per case reached.",
            )

        # 6. Quality gate evaluation (advisory on upload, authoritative on submission)
        quality_status, reason_codes, quality_scores = evaluate_image_quality(reencoded_bytes)

        # 7. Store re-encoded bytes in GridFS
        sha256_hash = hashlib.sha256(reencoded_bytes).hexdigest()
        random_suffix = secrets.token_hex(8)
        storage_filename = f"{case_id}_{site.value}_{view_type.value}_{random_suffix}.jpg"

        storage_id = await self.storage.save(
            filename=storage_filename,
            data=reencoded_bytes,
            content_type="image/jpeg",
            metadata={
                "case_id": case_id,
                "site": site.value,
                "view_type": view_type.value,
                "sha256": sha256_hash,
            },
        )

        # 8. Delete previous superseded file from GridFS if replacing
        now = datetime.now(UTC)
        if superseded_img:
            old_storage_id = superseded_img.get("storage_id")
            if old_storage_id:
                await self.storage.delete(old_storage_id)
            # Update existing record
            await self.db["images"].update_one(
                {"_id": superseded_img["_id"]},
                {
                    "$set": {
                        "storage_id": storage_id,
                        "quality_scores": quality_scores,
                        "quality_status": quality_status,
                        "reason_codes": reason_codes,
                        "sha256": sha256_hash,
                        "updated_at": now,
                    }
                },
            )
            image_record_id = str(superseded_img["_id"])
        else:
            # Insert new image record
            new_doc = {
                "case_id": case_id,
                "site": site.value,
                "view_type": view_type.value,
                "storage_id": storage_id,
                "quality_scores": quality_scores,
                "quality_status": quality_status,
                "reason_codes": reason_codes,
                "sha256": sha256_hash,
                "created_at": now,
                "updated_at": now,
            }
            res = await self.db["images"].insert_one(new_doc)
            image_record_id = str(res.inserted_id)

        # 9. Update case anatomical_sites array
        case_oid = ObjectId(case_id) if ObjectId.is_valid(case_id) else case_id
        await self.db["cases"].update_one(
            {"_id": case_oid},
            {"$addToSet": {"anatomical_sites": site.value}},
        )

        return ImageUploadResponse(
            id=image_record_id,
            case_id=case_id,
            site=site,
            view_type=view_type,
            quality_status=QualityStatus(quality_status),
            reason_codes=reason_codes,
            quality_scores=quality_scores,
            created_at=now,
        )

    async def get_images_for_case(self, case_id: str) -> list[dict[str, Any]]:
        """Retrieves all image records for a given case."""
        return await self.db["images"].find({"case_id": case_id}).to_list(length=50)

    async def get_image_by_id(self, image_id: str) -> dict[str, Any] | None:
        """Retrieves image document by its ID."""
        if not ObjectId.is_valid(image_id):
            return None
        return await self.db["images"].find_one({"_id": ObjectId(image_id)})
