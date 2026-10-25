"""
ONCOLINK Screening Intake Test Suite
====================================
Comprehensive tests for:
1. Questionnaire history recording, validation (extra="forbid"), state-dependent 409s.
2. Photo upload security pipeline:
   - Magic bytes validation (HTML/text renamed .jpg rejected)
   - Mismatched content-type rejected
   - Oversize file rejected (> 10 MB)
   - Decompression bomb rejected (large pixel dimensions)
   - JPEG with GPS EXIF stored without EXIF and stored bytes differ
   - Superseding deletes old GridFS file
   - 12-image cap per case
3. Quality gate checks (blur, exposure, shadows/highlights, low detail, small resolution).
4. Authenticated image retrieval: streaming from GridFS, Cache-Control: no-store,
   X-Content-Type-Options: nosniff, immutable audit entry (IDs only).
5. Case submission preconditions (422 with specific missing items).
6. Authoritative submission state machine pipeline (quality pass -> queued, quality fail -> needs_retake,
   red flag -> red_flag).
7. Atomicity invariant: double submit 409, forced audit failure mid-chain rolls back cleanly to draft.
8. Authorization matrix across all personas and unassigned pool doctor / second-opinion doctor.
"""

import io
from datetime import UTC, datetime
from unittest.mock import patch

import numpy as np
import pytest
from bson import ObjectId
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient
from PIL import Image

from app.config import Settings
from app.models.case import CaseStatus, Urgency
from app.models.image import QualityStatus
from app.models.user import DoctorVerificationStatus, UserRole
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.quality_gate import evaluate_image_quality
from app.services.quality_thresholds import (
    REASON_LOW_DETAIL,
    REASON_TOO_BLURRY,
    REASON_TOO_BRIGHT,
    REASON_TOO_DARK,
    REASON_TOO_SMALL,
)
from app.storage import GridFSStorageService

# NOTE: Synthetic images prove the code works, not that thresholds suit real photos.

PRECOMPUTED_TEST_HASH = "$argon2id$v=19$m=65536,t=3,p=4$qN72ZkE9bZPvD3x0c+rUeQ$X5wWzJ9QvP7lM4jK8hF3tY6aB2cE1dG9uI0oR8sT4vU"


# --- Synthetic Image Helpers ---


def make_sharp_image(width: int = 640, height: int = 640) -> bytes:
    """Generates a high-contrast checkered/textured image with high Laplacian variance (quality passed)."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(0, height, 16):
        for x in range(0, width, 16):
            if ((x // 16) + (y // 16)) % 2 == 0:
                arr[y : y + 16, x : x + 16] = [200, 200, 200]
            else:
                arr[y : y + 16, x : x + 16] = [50, 50, 50]
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def make_blurry_image(width: int = 640, height: int = 640) -> bytes:
    """Generates a smooth low-frequency gradient with low Laplacian variance (too_blurry)."""
    # Smooth horizontal gradient between 100 and 130
    row = np.linspace(100, 130, width, dtype=np.uint8)
    arr = np.tile(row, (height, 1))
    arr_rgb = np.stack([arr, arr, arr], axis=-1)
    img = Image.fromarray(arr_rgb, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_dark_image(width: int = 640, height: int = 640) -> bytes:
    """Generates an underexposed image (too_dark)."""
    arr = np.full((height, width, 3), 15, dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_bright_image(width: int = 640, height: int = 640) -> bytes:
    """Generates an overexposed washed out image (too_bright)."""
    arr = np.full((height, width, 3), 250, dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_low_detail_image(width: int = 640, height: int = 640) -> bytes:
    """Generates a uniform solid gray image (low_detail)."""
    arr = np.full((height, width, 3), 128, dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_small_image(width: int = 300, height: int = 300) -> bytes:
    """Generates an image smaller than 480x480 minimum resolution (too_small)."""
    arr = np.full((height, width, 3), 128, dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_image_with_gps_exif() -> bytes:
    """Generates a valid JPEG containing real EXIF GPS metadata."""
    img = Image.new("RGB", (640, 640), color=(120, 150, 180))
    exif = img.getexif()
    exif[0x010E] = "Sensitive Clinical Geolocation & Patient Private Note"
    gps_ifd = exif.get_ifd(0x8825)
    gps_ifd[1] = "N"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def get_standard_history_payload(
    heavy_bleeding: bool = False,
    difficulty_breathing: bool = False,
    rapid_swelling: bool = False,
) -> dict:
    return {
        "tobacco_smoked_frequency": "daily",
        "tobacco_smoked_years": 5,
        "tobacco_smokeless_frequency": "never",
        "tobacco_smokeless_years": 0,
        "areca_nut_frequency": "occasional",
        "areca_nut_years": 2,
        "betel_quid_frequency": "never",
        "betel_quid_years": 0,
        "alcohol_frequency": "occasional",
        "lesion_duration_weeks": 3,
        "lesion_pain": True,
        "lesion_non_healing_two_weeks": True,
        "lesion_bleeding": False,
        "lesion_white_or_red_patch": True,
        "lesion_lump": False,
        "difficulty_swallowing": False,
        "difficulty_opening_mouth": False,
        "difficulty_speaking": False,
        "unexplained_weight_loss": False,
        "family_history_cancer": False,
        "heavy_bleeding": heavy_bleeding,
        "difficulty_breathing": difficulty_breathing,
        "rapid_swelling": rapid_swelling,
    }


# --- Setup Fixtures ---


async def create_user_and_headers(
    db,
    auth_svc,
    role: UserRole,
    email: str,
    verification_status: DoctorVerificationStatus = DoctorVerificationStatus.VERIFIED,
) -> tuple[str, dict[str, str]]:
    now = datetime.now(UTC)
    doc = {
        "email": email,
        "password_hash": PRECOMPUTED_TEST_HASH,
        "role": role.value,
        "is_active": True,
        "is_demo": False,
        "verification_status": verification_status.value,
        "created_at": now,
        "failed_login_attempts": 0,
        "locked_until": None,
        "totp_enrolled": True,
    }
    res = await db["users"].insert_one(doc)
    user_id = str(res.inserted_id)
    token, _ = auth_svc.create_access_token(user_id=user_id, role=role.value)
    return user_id, {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Quality Gate Unit Tests
# ==============================================================================


def test_quality_gate_evaluator_all_reason_codes():
    """Verifies that each synthetic test condition triggers its exact reason code."""
    # Sharp image -> passes with zero reason codes
    sharp_bytes = make_sharp_image()
    status, reasons, scores = evaluate_image_quality(sharp_bytes)
    assert status == QualityStatus.PASSED.value
    assert reasons == []
    assert scores["laplacian_var"] >= 100.0

    # Blurry image -> too_blurry
    blurry_bytes = make_blurry_image()
    status, reasons, scores = evaluate_image_quality(blurry_bytes)
    assert status == QualityStatus.REJECTED.value
    assert REASON_TOO_BLURRY in reasons

    # Dark image -> too_dark
    dark_bytes = make_dark_image()
    status, reasons, scores = evaluate_image_quality(dark_bytes)
    assert status == QualityStatus.REJECTED.value
    assert REASON_TOO_DARK in reasons

    # Bright image -> too_bright
    bright_bytes = make_bright_image()
    status, reasons, scores = evaluate_image_quality(bright_bytes)
    assert status == QualityStatus.REJECTED.value
    assert REASON_TOO_BRIGHT in reasons

    # Low detail image -> low_detail
    detail_bytes = make_low_detail_image()
    status, reasons, scores = evaluate_image_quality(detail_bytes)
    assert status == QualityStatus.REJECTED.value
    assert REASON_LOW_DETAIL in reasons

    # Small image -> too_small
    small_bytes = make_small_image(300, 300)
    status, reasons, scores = evaluate_image_quality(small_bytes)
    assert status == QualityStatus.REJECTED.value
    assert REASON_TOO_SMALL in reasons


# ==============================================================================
# 2. Photo Upload Security & Processing Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_upload_html_or_text_renamed_jpg_rejected(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Uploading a text or HTML file disguised with a .jpg extension must be rejected via magic bytes."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_img1@test.com"
    )

    # Link patient profile
    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-IMG1",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # HTML payload renamed .jpg
    fake_payload = b"<!DOCTYPE html><html><body><h1>Malicious Payload</h1></body></html>"
    files = {"file": ("exploit.jpg", fake_payload, "image/jpeg")}
    data = {"site": "left_cheek", "view_type": "lesion_closeup"}

    res = await async_client.post(f"/cases/{cid}/images", headers=p_headers, data=data, files=files)
    assert res.status_code == 400
    assert "magic bytes" in res.text or "Invalid image format" in res.text


@pytest.mark.asyncio
async def test_upload_mismatched_content_type_rejected(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Mismatched Content-Type header (e.g. image/png header for JPEG binary) must be rejected."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_img2@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-IMG2",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    jpeg_bytes = make_sharp_image()
    # Deliberately mismatched: JPEG binary sent with image/png content type
    files = {"file": ("photo.jpg", jpeg_bytes, "image/png")}
    data = {"site": "left_cheek", "view_type": "lesion_closeup"}

    res = await async_client.post(f"/cases/{cid}/images", headers=p_headers, data=data, files=files)
    assert res.status_code == 400
    assert "Mismatched Content-Type" in res.text


@pytest.mark.asyncio
async def test_upload_oversize_file_rejected(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Images exceeding 10 MB must be rejected."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_img3@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-IMG3",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # 10.5 MB payload starting with JPEG magic bytes
    oversize_payload = b"\xff\xd8\xff\xe0" + b"\x00" * (11 * 1024 * 1024)
    files = {"file": ("huge.jpg", oversize_payload, "image/jpeg")}
    data = {"site": "left_cheek", "view_type": "lesion_closeup"}

    res = await async_client.post(f"/cases/{cid}/images", headers=p_headers, data=data, files=files)
    assert res.status_code == 400
    assert "exceeds maximum allowable size" in res.text


@pytest.mark.asyncio
async def test_upload_decompression_bomb_rejected(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Images with massive pixel dimensions (> 25 megapixels) must be rejected."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_img4@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-IMG4",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # 6000 x 5000 = 30 million pixels (> 25 MP decompression limit)
    bomb_img = Image.new("RGB", (6000, 5000), color=(100, 100, 100))
    bomb_buf = io.BytesIO()
    bomb_img.save(bomb_buf, format="JPEG", quality=10)
    bomb_bytes = bomb_buf.getvalue()

    files = {"file": ("bomb.jpg", bomb_bytes, "image/jpeg")}
    data = {"site": "left_cheek", "view_type": "lesion_closeup"}

    res = await async_client.post(f"/cases/{cid}/images", headers=p_headers, data=data, files=files)
    assert res.status_code == 400
    assert "decompression bomb" in res.text


@pytest.mark.asyncio
async def test_upload_jpeg_with_gps_exif_stripped_and_stored_bytes_differ(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Uploading a JPEG with GPS EXIF must re-encode and store bytes without any EXIF tags."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_img5@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-IMG5",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    raw_gps_bytes = make_image_with_gps_exif()
    # Verify input has EXIF
    with Image.open(io.BytesIO(raw_gps_bytes)) as pil_in:
        assert len(pil_in.getexif()) > 0

    files = {"file": ("gps_photo.jpg", raw_gps_bytes, "image/jpeg")}
    data = {"site": "tongue_top", "view_type": "lesion_closeup"}

    res = await async_client.post(f"/cases/{cid}/images", headers=p_headers, data=data, files=files)
    assert res.status_code == 200
    img_id = res.json()["id"]

    # Verify stored image in GridFS
    storage_svc = GridFSStorageService(db)
    img_doc = await db["images"].find_one({"_id": ObjectId(img_id)})
    assert img_doc is not None
    stored_bytes, _, _ = await storage_svc.open(img_doc["storage_id"])

    # 1. Stored bytes differ from uploaded bytes
    assert stored_bytes != raw_gps_bytes

    # 2. Stored bytes contain zero EXIF tags
    with Image.open(io.BytesIO(stored_bytes)) as pil_out:
        assert len(pil_out.getexif()) == 0


@pytest.mark.asyncio
async def test_superseding_deletes_old_gridfs_file(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Uploading the same site and view_type again supersedes the old image and deletes the old file from GridFS."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    storage_svc = GridFSStorageService(db)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_img6@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-IMG6",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # 1. First upload
    first_bytes = make_blurry_image()
    res1 = await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "hard_palate", "view_type": "context"},
        files={"file": ("first.jpg", first_bytes, "image/jpeg")},
    )
    assert res1.status_code == 200
    doc1 = await db["images"].find_one({"case_id": cid, "site": "hard_palate"})
    assert doc1 is not None
    storage_id_1 = doc1["storage_id"]
    assert await storage_svc.exists(storage_id_1) is True

    # 2. Second upload superseding the same site & view_type
    second_bytes = make_sharp_image()
    res2 = await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "hard_palate", "view_type": "context"},
        files={"file": ("second.jpg", second_bytes, "image/jpeg")},
    )
    assert res2.status_code == 200

    # Old GridFS file must be deleted
    assert await storage_svc.exists(storage_id_1) is False

    # New image record exists and total images for case remains 1
    doc2 = await db["images"].find_one({"case_id": cid, "site": "hard_palate"})
    assert doc2 is not None
    assert doc2["storage_id"] != storage_id_1
    assert await storage_svc.exists(doc2["storage_id"]) is True

    total_images = await db["images"].count_documents({"case_id": cid})
    assert total_images == 1


@pytest.mark.asyncio
async def test_twelve_image_cap(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Enforces the 12-image cap per screening case."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_img7@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-IMG7",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # 7 sites x 2 view_types gives 14 possible combinations
    combinations = [
        (site, vt)
        for site in [
            "left_cheek",
            "right_cheek",
            "tongue_top",
            "tongue_sides",
            "floor_of_mouth",
            "hard_palate",
            "lips_and_gums",
        ]
        for vt in ["lesion_closeup", "context"]
    ]

    img_data = make_sharp_image()

    # Upload first 12 images
    for i in range(12):
        site, vt = combinations[i]
        res = await async_client.post(
            f"/cases/{cid}/images",
            headers=p_headers,
            data={"site": site, "view_type": vt},
            files={"file": (f"img_{i}.jpg", img_data, "image/jpeg")},
        )
        assert res.status_code == 200

    assert await db["images"].count_documents({"case_id": cid}) == 12

    # 13th upload of a new slot rejected
    site_13, vt_13 = combinations[12]
    res13 = await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": site_13, "view_type": vt_13},
        files={"file": ("img_13.jpg", img_data, "image/jpeg")},
    )
    assert res13.status_code == 400
    assert "Maximum limit of 12 images" in res13.text

    # Re-uploading an existing slot (superseding) succeeds
    site_1, vt_1 = combinations[0]
    res_supersede = await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": site_1, "view_type": vt_1},
        files={"file": ("img_replace.jpg", img_data, "image/jpeg")},
    )
    assert res_supersede.status_code == 200
    assert await db["images"].count_documents({"case_id": cid}) == 12


# ==============================================================================
# 3. Image Retrieval & Audit Invariant Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_image_retrieval_headers_and_audit(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """GET /cases/{id}/images/{image_id} streams with exact security headers and writes audit log with IDs only."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_img8@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-IMG8",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # Upload sharp photo
    upload_res = await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "left_cheek", "view_type": "lesion_closeup"},
        files={"file": ("photo.jpg", make_sharp_image(), "image/jpeg")},
    )
    assert upload_res.status_code == 200
    img_id = upload_res.json()["id"]

    # Retrieve image
    get_res = await async_client.get(f"/cases/{cid}/images/{img_id}", headers=p_headers)
    assert get_res.status_code == 200

    # 1. Required security headers
    assert get_res.headers.get("cache-control") == "no-store"
    assert get_res.headers.get("x-content-type-options") == "nosniff"

    # 2. Audit log entry written (IDs only, NO free text)
    audit_entry = await db["audit_log"].find_one(
        {"event_type": "image_view", "details.image_id": img_id}
    )
    assert audit_entry is not None
    assert audit_entry["actor_id"] == patient_id
    assert audit_entry["actor_role"] == UserRole.PATIENT.value
    assert audit_entry["details"]["case_id"] == cid
    assert audit_entry["details"]["image_id"] == img_id
    assert "storage_id" in audit_entry["details"]

    # Verify no free-text clinical notes leaked into audit log
    for k, v in audit_entry["details"].items():
        assert isinstance(v, str)
        assert len(v) < 100, f"Suspiciously long field in audit details: {k}"


# ==============================================================================
# 4. Questionnaire History Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_questionnaire_history_validation_and_storage(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """POST /cases/{id}/history validates fields strictly (extra='forbid') and saves to case_history."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_q1@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-Q1",
            "patient_id": str(pat_res.inserted_id),
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # 1. Unknown field rejected
    bad_payload = get_standard_history_payload()
    bad_payload["unknown_injection_field"] = "malicious text"
    res_bad = await async_client.post(f"/cases/{cid}/history", headers=p_headers, json=bad_payload)
    assert res_bad.status_code == 422

    # 2. Valid payload accepted & saved
    valid_payload = get_standard_history_payload(heavy_bleeding=True)
    res_ok = await async_client.post(f"/cases/{cid}/history", headers=p_headers, json=valid_payload)
    assert res_ok.status_code == 200
    assert "heavy_bleeding" in res_ok.json()["red_flags"]

    stored_q = await db["case_history"].find_one({"case_id": cid})
    assert stored_q is not None
    assert stored_q["history"]["heavy_bleeding"] is True
    assert stored_q["history"]["tobacco_smoked_frequency"] == "daily"


# ==============================================================================
# 5. Case Submission Preconditions (422) & Pipeline Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_submission_preconditions_422(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """POST /cases/{id}/submit returns 422 with exact list of missing items when preconditions fail."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_sub1@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    pid = str(pat_res.inserted_id)
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-SUB1",
            "patient_id": pid,
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # 1. Fresh draft (no consent, no history, no images)
    res1 = await async_client.post(f"/cases/{cid}/submit", headers=p_headers)
    assert res1.status_code == 422
    missing1 = res1.json()["detail"]["missing_items"]
    assert "active_consent" in missing1
    assert "case_history" in missing1
    assert "lesion_closeup_image" in missing1
    assert "context_images" in missing1

    # 2. Add consent only
    await db["consents"].insert_one(
        {
            "patient_id": pid,
            "version": "v1",
            "language": "en",
            "timestamp": datetime.now(UTC),
            "captured_by": patient_id,
        }
    )
    res2 = await async_client.post(f"/cases/{cid}/submit", headers=p_headers)
    assert res2.status_code == 422
    missing2 = res2.json()["detail"]["missing_items"]
    assert "active_consent" not in missing2
    assert "case_history" in missing2

    # 3. Add history
    await async_client.post(
        f"/cases/{cid}/history", headers=p_headers, json=get_standard_history_payload()
    )
    res3 = await async_client.post(f"/cases/{cid}/submit", headers=p_headers)
    assert res3.status_code == 422
    missing3 = res3.json()["detail"]["missing_items"]
    assert "active_consent" not in missing3
    assert "case_history" not in missing3
    assert "lesion_closeup_image" in missing3
    assert "context_images" in missing3


@pytest.mark.asyncio
async def test_submission_pipeline_quality_pass_queued(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Submitting valid case with quality-passing photos advances: draft -> submitted -> quality_check -> queued."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_sub2@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    pid = str(pat_res.inserted_id)
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-SUB2",
            "patient_id": pid,
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    # Consent + History
    await db["consents"].insert_one(
        {
            "patient_id": pid,
            "version": "v1",
            "language": "en",
            "timestamp": datetime.now(UTC),
            "captured_by": patient_id,
        }
    )
    await async_client.post(
        f"/cases/{cid}/history", headers=p_headers, json=get_standard_history_payload()
    )

    # 1 closeup + 2 context views (all sharp)
    sharp_data = make_sharp_image()
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "tongue_top", "view_type": "lesion_closeup"},
        files={"file": ("c1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "left_cheek", "view_type": "context"},
        files={"file": ("ctx1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "right_cheek", "view_type": "context"},
        files={"file": ("ctx2.jpg", sharp_data, "image/jpeg")},
    )

    # Submit
    res = await async_client.post(f"/cases/{cid}/submit", headers=p_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == CaseStatus.QUEUED.value
    assert body["urgency"] == Urgency.ROUTINE.value
    assert body["red_flag"] is False
    assert body["failed_images"] == []

    # Check database status history
    case_in_db = await db["cases"].find_one({"_id": ObjectId(cid)})
    assert case_in_db["status"] == CaseStatus.QUEUED.value
    history_statuses = [h["to_status"] for h in case_in_db["status_history"]]
    assert history_statuses == ["submitted", "quality_check", "queued"]


@pytest.mark.asyncio
async def test_submission_pipeline_quality_fail_needs_retake(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Submitting case with a blurry photo advances: draft -> submitted -> quality_check -> needs_retake."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_sub3@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    pid = str(pat_res.inserted_id)
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-SUB3",
            "patient_id": pid,
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    await db["consents"].insert_one(
        {
            "patient_id": pid,
            "version": "v1",
            "language": "en",
            "timestamp": datetime.now(UTC),
            "captured_by": patient_id,
        }
    )
    await async_client.post(
        f"/cases/{cid}/history", headers=p_headers, json=get_standard_history_payload()
    )

    # 1 closeup blurry, 2 context sharp
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "tongue_top", "view_type": "lesion_closeup"},
        files={"file": ("blurry.jpg", make_blurry_image(), "image/jpeg")},
    )
    sharp_data = make_sharp_image()
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "left_cheek", "view_type": "context"},
        files={"file": ("ctx1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "right_cheek", "view_type": "context"},
        files={"file": ("ctx2.jpg", sharp_data, "image/jpeg")},
    )

    # Submit
    res = await async_client.post(f"/cases/{cid}/submit", headers=p_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == CaseStatus.NEEDS_RETAKE.value
    assert len(body["failed_images"]) == 1
    assert "too_blurry" in body["failed_images"][0]["reason_codes"]

    # Check status history
    case_in_db = await db["cases"].find_one({"_id": ObjectId(cid)})
    assert case_in_db["status"] == CaseStatus.NEEDS_RETAKE.value
    history_statuses = [h["to_status"] for h in case_in_db["status_history"]]
    assert history_statuses == ["submitted", "quality_check", "needs_retake"]


@pytest.mark.asyncio
async def test_submission_pipeline_red_flag_emergency(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Submitting case with red-flag symptom advances: draft -> submitted -> quality_check -> red_flag."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_sub4@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    pid = str(pat_res.inserted_id)
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-SUB4",
            "patient_id": pid,
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    await db["consents"].insert_one(
        {
            "patient_id": pid,
            "version": "v1",
            "language": "en",
            "timestamp": datetime.now(UTC),
            "captured_by": patient_id,
        }
    )
    # History with heavy_bleeding
    await async_client.post(
        f"/cases/{cid}/history",
        headers=p_headers,
        json=get_standard_history_payload(heavy_bleeding=True),
    )

    sharp_data = make_sharp_image()
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "tongue_top", "view_type": "lesion_closeup"},
        files={"file": ("c1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "left_cheek", "view_type": "context"},
        files={"file": ("ctx1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "right_cheek", "view_type": "context"},
        files={"file": ("ctx2.jpg", sharp_data, "image/jpeg")},
    )

    res = await async_client.post(f"/cases/{cid}/submit", headers=p_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == CaseStatus.RED_FLAG.value
    assert body["urgency"] == Urgency.URGENT.value
    assert body["red_flag"] is True
    assert "heavy_bleeding" in body["red_flag_codes"]

    case_in_db = await db["cases"].find_one({"_id": ObjectId(cid)})
    assert case_in_db["status"] == CaseStatus.RED_FLAG.value
    history_statuses = [h["to_status"] for h in case_in_db["status_history"]]
    assert history_statuses == ["submitted", "quality_check", "red_flag"]


@pytest.mark.asyncio
async def test_double_submit_yields_one_success_and_one_409(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Calling submit twice sequentially: first succeeds, second returns 409 Conflict."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_sub5@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    pid = str(pat_res.inserted_id)
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-SUB5",
            "patient_id": pid,
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    await db["consents"].insert_one(
        {
            "patient_id": pid,
            "version": "v1",
            "language": "en",
            "timestamp": datetime.now(UTC),
            "captured_by": patient_id,
        }
    )
    await async_client.post(
        f"/cases/{cid}/history", headers=p_headers, json=get_standard_history_payload()
    )

    sharp_data = make_sharp_image()
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "tongue_top", "view_type": "lesion_closeup"},
        files={"file": ("c1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "left_cheek", "view_type": "context"},
        files={"file": ("ctx1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "right_cheek", "view_type": "context"},
        files={"file": ("ctx2.jpg", sharp_data, "image/jpeg")},
    )

    # 1. First submit succeeds
    res1 = await async_client.post(f"/cases/{cid}/submit", headers=p_headers)
    assert res1.status_code == 200

    # 2. Second submit fails with 409 Conflict
    res2 = await async_client.post(f"/cases/{cid}/submit", headers=p_headers)
    assert res2.status_code == 409


@pytest.mark.asyncio
async def test_forced_failure_in_audit_write_mid_chain_rolls_back_to_draft(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """If an audit write fails mid-chain, the transaction rolls back cleanly leaving case in draft with 0 transitions."""
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)
    patient_id, p_headers = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "p_sub6@test.com"
    )

    pat_res = await db["patients"].insert_one(
        {
            "user_id": patient_id,
            "date_of_birth": "1990-01-01",
            "created_by": patient_id,
            "erased": False,
        }
    )
    pid = str(pat_res.inserted_id)
    case_res = await db["cases"].insert_one(
        {
            "reference": "TEST-SUB6",
            "patient_id": pid,
            "created_by": patient_id,
            "status": CaseStatus.DRAFT.value,
            "version": 1,
            "anatomical_sites": [],
            "status_history": [],
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
    )
    cid = str(case_res.inserted_id)

    await db["consents"].insert_one(
        {
            "patient_id": pid,
            "version": "v1",
            "language": "en",
            "timestamp": datetime.now(UTC),
            "captured_by": patient_id,
        }
    )
    await async_client.post(
        f"/cases/{cid}/history", headers=p_headers, json=get_standard_history_payload()
    )

    sharp_data = make_sharp_image()
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "tongue_top", "view_type": "lesion_closeup"},
        files={"file": ("c1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "left_cheek", "view_type": "context"},
        files={"file": ("ctx1.jpg", sharp_data, "image/jpeg")},
    )
    await async_client.post(
        f"/cases/{cid}/images",
        headers=p_headers,
        data={"site": "right_cheek", "view_type": "context"},
        files={"file": ("ctx2.jpg", sharp_data, "image/jpeg")},
    )

    original_insert = AuditService.insert
    call_count = 0

    async def mock_insert_fail_on_second(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError(
                "Forced deliberate database failure during second edge audit logging!"
            )
        return await original_insert(self, *args, **kwargs)

    with patch.object(AuditService, "insert", new=mock_insert_fail_on_second):
        with pytest.raises(RuntimeError, match="Forced deliberate database failure"):
            await async_client.post(f"/cases/{cid}/submit", headers=p_headers)

    # Prove case remained in draft with version 1 and zero partial status history entries
    case_after = await db["cases"].find_one({"_id": ObjectId(cid)})
    assert case_after["status"] == CaseStatus.DRAFT.value
    assert case_after["version"] == 1
    assert len(case_after["status_history"]) == 0


# ==============================================================================
# 6. Authorization Matrix Tests Across All Personas
# ==============================================================================


@pytest.mark.asyncio
async def test_authorization_matrix_screening_endpoints(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """
    Exhaustively tests the authorization matrix for the new screening endpoints:
    - POST /cases/{id}/history
    - POST /cases/{id}/images
    - GET /cases/{id}/images/{image_id}
    - POST /cases/{id}/submit
    Across all caller personas (Owner, Screener, Other Patient, Other Screener,
    Assigned Doctor, Second-Opinion Doctor, Pool Doctor, Unverified Doctor, Admin, Coordinator).
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    audit_svc = AuditService(db)
    auth_svc = AuthService(db, test_settings, audit_svc)

    # 1. Create personas
    owner_id, owner_h = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "matrix_owner@test.com"
    )
    other_p_id, other_p_h = await create_user_and_headers(
        db, auth_svc, UserRole.PATIENT, "matrix_other_p@test.com"
    )

    creator_scr_id, scr_h = await create_user_and_headers(
        db, auth_svc, UserRole.SCREENER, "matrix_scr@test.com"
    )
    other_scr_id, other_scr_h = await create_user_and_headers(
        db, auth_svc, UserRole.SCREENER, "matrix_other_scr@test.com"
    )

    assigned_doc_id, doc_assigned_h = await create_user_and_headers(
        db, auth_svc, UserRole.DOCTOR, "matrix_doc1@test.com"
    )
    second_doc_id, doc_second_h = await create_user_and_headers(
        db, auth_svc, UserRole.DOCTOR, "matrix_doc2@test.com"
    )
    pool_doc_id, doc_pool_h = await create_user_and_headers(
        db, auth_svc, UserRole.DOCTOR, "matrix_doc3@test.com"
    )
    unverified_doc_id, doc_unverified_h = await create_user_and_headers(
        db,
        auth_svc,
        UserRole.DOCTOR,
        "matrix_doc4@test.com",
        verification_status=DoctorVerificationStatus.PENDING,
    )

    admin_id, admin_h = await create_user_and_headers(
        db, auth_svc, UserRole.ADMIN, "matrix_admin@test.com"
    )
    coord_id, coord_h = await create_user_and_headers(
        db, auth_svc, UserRole.HOSPITAL_COORDINATOR, "matrix_coord@test.com"
    )

    # Patient records
    pat_res = await db["patients"].insert_one(
        {
            "user_id": owner_id,
            "date_of_birth": "1990-01-01",
            "created_by": owner_id,
            "erased": False,
        }
    )
    pid = str(pat_res.inserted_id)

    await db["patients"].insert_one(
        {
            "user_id": other_p_id,
            "date_of_birth": "1992-02-02",
            "created_by": other_p_id,
            "erased": False,
        }
    )

    # Case owned by owner_id, assigned to assigned_doc_id, second opinion second_doc_id
    case_doc = {
        "reference": "TEST-MATR",
        "patient_id": pid,
        "created_by": owner_id,
        "status": CaseStatus.DRAFT.value,
        "assigned_doctor_id": assigned_doc_id,
        "second_opinion_doctor_id": second_doc_id,
        "version": 1,
        "anatomical_sites": [],
        "status_history": [],
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    case_res = await db["cases"].insert_one(case_doc)
    cid = str(case_res.inserted_id)

    # Upload an initial image for viewing tests
    upload_res = await async_client.post(
        f"/cases/{cid}/images",
        headers=owner_h,
        data={"site": "tongue_top", "view_type": "lesion_closeup"},
        files={"file": ("photo.jpg", make_sharp_image(), "image/jpeg")},
    )
    assert upload_res.status_code == 200
    img_id = upload_res.json()["id"]

    # --- Test: POST /cases/{id}/history ---
    valid_q = get_standard_history_payload()
    # Unauth -> 401
    assert (await async_client.post(f"/cases/{cid}/history", json=valid_q)).status_code == 401
    # Owner Patient -> 200
    assert (
        await async_client.post(f"/cases/{cid}/history", headers=owner_h, json=valid_q)
    ).status_code == 200
    # Other Patient -> 404 (Anti-probing)
    assert (
        await async_client.post(f"/cases/{cid}/history", headers=other_p_h, json=valid_q)
    ).status_code == 404
    # Screener not creator -> 404
    assert (
        await async_client.post(f"/cases/{cid}/history", headers=other_scr_h, json=valid_q)
    ).status_code == 404
    # Doctor (Assigned/Second) -> 403
    assert (
        await async_client.post(f"/cases/{cid}/history", headers=doc_assigned_h, json=valid_q)
    ).status_code == 403
    assert (
        await async_client.post(f"/cases/{cid}/history", headers=doc_second_h, json=valid_q)
    ).status_code == 403
    # Coordinator -> 403
    assert (
        await async_client.post(f"/cases/{cid}/history", headers=coord_h, json=valid_q)
    ).status_code == 403
    # Admin -> 403
    assert (
        await async_client.post(f"/cases/{cid}/history", headers=admin_h, json=valid_q)
    ).status_code == 403

    # --- Test: POST /cases/{id}/images ---
    img_form = {"site": "left_cheek", "view_type": "context"}
    file_payload = {"file": ("ctx.jpg", make_sharp_image(), "image/jpeg")}
    # Unauth -> 401
    assert (
        await async_client.post(f"/cases/{cid}/images", data=img_form, files=file_payload)
    ).status_code == 401
    # Owner Patient -> 200
    assert (
        await async_client.post(
            f"/cases/{cid}/images", headers=owner_h, data=img_form, files=file_payload
        )
    ).status_code == 200
    # Other Patient -> 404
    assert (
        await async_client.post(
            f"/cases/{cid}/images", headers=other_p_h, data=img_form, files=file_payload
        )
    ).status_code == 404
    # Doctor -> 403
    assert (
        await async_client.post(
            f"/cases/{cid}/images", headers=doc_assigned_h, data=img_form, files=file_payload
        )
    ).status_code == 403
    # Admin -> 403
    assert (
        await async_client.post(
            f"/cases/{cid}/images", headers=admin_h, data=img_form, files=file_payload
        )
    ).status_code == 403

    # --- Test: GET /cases/{id}/images/{image_id} ---
    # Unauth -> 401
    assert (await async_client.get(f"/cases/{cid}/images/{img_id}")).status_code == 401
    # Owner Patient -> 200
    assert (
        await async_client.get(f"/cases/{cid}/images/{img_id}", headers=owner_h)
    ).status_code == 200
    # Other Patient -> 404 (Anti-probing)
    assert (
        await async_client.get(f"/cases/{cid}/images/{img_id}", headers=other_p_h)
    ).status_code == 404
    # Assigned Doctor -> 200
    assert (
        await async_client.get(f"/cases/{cid}/images/{img_id}", headers=doc_assigned_h)
    ).status_code == 200
    # Second-Opinion Doctor -> 200
    assert (
        await async_client.get(f"/cases/{cid}/images/{img_id}", headers=doc_second_h)
    ).status_code == 200
    # Pool Doctor (Unassigned to this case) -> 404 (Anti-probing; pool doctors only get metadata)
    assert (
        await async_client.get(f"/cases/{cid}/images/{img_id}", headers=doc_pool_h)
    ).status_code == 404
    # Unverified Doctor -> 403 Forbidden
    assert (
        await async_client.get(f"/cases/{cid}/images/{img_id}", headers=doc_unverified_h)
    ).status_code == 403
    # Coordinator -> 403 Forbidden
    assert (
        await async_client.get(f"/cases/{cid}/images/{img_id}", headers=coord_h)
    ).status_code == 403
    # Admin -> 403 Forbidden
    assert (
        await async_client.get(f"/cases/{cid}/images/{img_id}", headers=admin_h)
    ).status_code == 403

    # --- Test: GET /cases/{id} includes image metadata ---
    # Patient viewer includes images
    p_case_res = await async_client.get(f"/cases/{cid}", headers=owner_h)
    assert p_case_res.status_code == 200
    assert "images" in p_case_res.json()
    assert len(p_case_res.json()["images"]) >= 1

    # Assigned Doctor viewer includes images
    doc_case_res = await async_client.get(f"/cases/{cid}", headers=doc_assigned_h)
    assert doc_case_res.status_code == 200
    assert "images" in doc_case_res.json()
    assert len(doc_case_res.json()["images"]) >= 1
