import hashlib

import pytest
from httpx import AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.consent_texts import CONSENT_TEXT, CONSENT_VERSION


@pytest.mark.asyncio
async def test_get_current_consent_endpoint(async_client: AsyncClient):
    """GET /consent/current returns versioned plain-language consent text and canonical hash."""
    res = await async_client.get("/consent/current")
    assert res.status_code == 200
    data = res.json()

    assert data["version"] == CONSENT_VERSION
    assert data["language"] == "en"
    assert "not a medical device" in data["text"].lower()
    assert "research" in data["text"].lower()
    assert "withdraw" in data["text"].lower()

    expected_hash = hashlib.sha256(CONSENT_TEXT.strip().encode("utf-8")).hexdigest()
    assert data["text_hash"] == expected_hash


@pytest.mark.asyncio
async def test_registration_rejected_without_consent(async_client: AsyncClient):
    """Patient registration fails if consent is not accepted or version is outdated."""
    # 1. consent_accepted is False
    res1 = await async_client.post(
        "/auth/register",
        json={
            "email": "no_consent@example.com",
            "password": "Password123!",
            "date_of_birth": "1990-01-01",
            "consent_version": "v1",
            "consent_accepted": False,
        },
    )
    assert res1.status_code == 400
    assert "accepted" in res1.json()["detail"].lower()

    # 2. Outdated consent version
    res2 = await async_client.post(
        "/auth/register",
        json={
            "email": "outdated_consent@example.com",
            "password": "Password123!",
            "date_of_birth": "1990-01-01",
            "consent_version": "v0-deprecated",
            "consent_accepted": True,
        },
    )
    assert res2.status_code == 400
    assert "outdated" in res2.json()["detail"].lower()


@pytest.mark.asyncio
async def test_registration_creates_immutable_consent_record(
    async_client: AsyncClient,
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
):
    """Patient registration with valid consent writes an immutable record in consents collection."""
    db = test_mongo_client[test_settings.mongo_db_name]

    res = await async_client.post(
        "/auth/register",
        json={
            "email": "consenting_patient@example.com",
            "password": "ValidPassword123!",
            "date_of_birth": "1990-01-01",
            "consent_version": "v1",
            "consent_accepted": True,
        },
    )
    assert res.status_code == 201
    user_id = res.json()["user_id"]

    # Verify document in MongoDB consents collection
    consent_doc = await db["consents"].find_one({"user_id": user_id})
    assert consent_doc is not None
    assert consent_doc["version"] == "v1"
    assert consent_doc["language"] == "en"
    assert consent_doc["captured_by"] == "self"
    assert "text_hash" in consent_doc
    assert consent_doc["accepted_at"] is not None
