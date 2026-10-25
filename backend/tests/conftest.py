import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import Settings
from app.database import close_db, init_db
from app.main import create_app


@pytest.fixture
def test_settings() -> Settings:
    """Fixture providing isolated test settings targeting a dedicated test database."""
    default_test_uri = (
        "mongodb://oncolink_app:oncolink_app_dev_password_change_me@mongodb:27017/oncolink_test"
        "?replicaSet=rs0&authSource=oncolink"
    )
    mongo_uri = os.getenv("MONGO_TEST_URI", default_test_uri)

    return Settings(
        project_name="OncoLink-Test",
        environment="testing",
        log_level="WARNING",
        mongo_uri=mongo_uri,
        mongo_db_name="oncolink_test",
        jwt_secret="test_jwt_secret_must_be_very_long_and_secure_64_chars_for_tests!",
        totp_encryption_key="mO4YZOqlOWz_0Q2XD5Da5sfoL6n13xlA8PRLnvpI3Q8=",
        demo_patient_email="demo.patient@oncolink.local",
        demo_patient_password="Patient#Sec2026!P",
        demo_screener_email="demo.screener@oncolink.local",
        demo_screener_password="Screener#Sec2026!S",
        demo_doctor_email="demo.doctor@oncolink.local",
        demo_doctor_password="Doctor#Sec2026!D",
        demo_hospital_coordinator_email="demo.coordinator@oncolink.local",
        demo_hospital_coordinator_password="Coord#Sec2026!C",
        demo_admin_email="demo.admin@oncolink.local",
        demo_admin_password="Admin#Sec2026!A",
    )


@pytest_asyncio.fixture
async def test_mongo_client(test_settings: Settings) -> AsyncGenerator[AsyncIOMotorClient, None]:
    """Provide connected AsyncIOMotorClient connected to the replica set test database."""
    client = AsyncIOMotorClient(
        test_settings.mongo_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    # Ensure ping succeeds
    await client.admin.command("ping")
    yield client
    client.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_test_db(
    test_mongo_client: AsyncIOMotorClient, test_settings: Settings
) -> AsyncGenerator[None, None]:
    """Clean the test collections before and after each test run."""
    db = test_mongo_client[test_settings.mongo_db_name]
    yield
    # Drop all test collections after test execution
    for col in await db.list_collection_names():
        if not col.startswith("system."):
            await db[col].drop()


@pytest_asyncio.fixture
async def async_client(test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """Fixture providing an AsyncClient targeting the configured FastAPI application."""
    app = create_app(test_settings)
    await init_db(test_settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await close_db()
