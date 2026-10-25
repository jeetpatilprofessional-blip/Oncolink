import pytest
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorClientSession

from app.config import Settings
from app.database import run_transaction


@pytest.mark.asyncio
async def test_transaction_rolls_back_when_second_write_fails(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
) -> None:
    """
    Prove that an atomic transaction rolls back all prior writes if a subsequent write fails.
    Simulates a case status transition where the case document update succeeds, but the
    audit log insertion fails, ensuring zero partial state corruption.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    cases_collection = db["cases"]
    audit_collection = db["audit_log"]

    # Pre-create the collections in the replica set database (MongoDB requires collections
    # to exist prior to transactional operations in certain replica set configurations)
    await db.create_collection("cases")
    await db.create_collection("audit_log")

    case_id = "CASE-TRANSACTION-TEST-001"
    initial_doc = {"case_id": case_id, "status": "draft"}
    await cases_collection.insert_one(initial_doc)

    # Define an atomic transactional operation where step 1 updates the case status,
    # and step 2 deliberately fails before completion.
    async def failing_transaction(session: AsyncIOMotorClientSession) -> None:
        # Step 1: Update case status inside transaction session
        await cases_collection.update_one(
            {"case_id": case_id},
            {"$set": {"status": "submitted"}},
            session=session,
        )

        # Step 2: Simulate an unexpected failure during the audit log write
        raise RuntimeError("Simulated database failure during audit log insertion")

    # Execute the transaction and expect the raised exception
    with pytest.raises(RuntimeError, match="Simulated database failure"):
        await run_transaction(test_mongo_client, failing_transaction)

    # Verify state outside of the transaction session:
    # The case status MUST still be "draft", proving the update in Step 1 was rolled back!
    case_in_db = await cases_collection.find_one({"case_id": case_id})
    assert case_in_db is not None
    assert case_in_db["status"] == "draft", "Status was not rolled back after transaction failure!"

    # And audit log MUST have 0 records
    audit_count = await audit_collection.count_documents({})
    assert audit_count == 0, "Audit log contains writes that should have been rolled back!"


@pytest.mark.asyncio
async def test_transaction_commits_both_writes_on_success(
    test_mongo_client: AsyncIOMotorClient,
    test_settings: Settings,
) -> None:
    """
    Verify that an atomic transaction successfully commits both writes when no errors occur.
    """
    db = test_mongo_client[test_settings.mongo_db_name]
    cases_collection = db["cases"]
    audit_collection = db["audit_log"]

    # Pre-create collections if not already created
    if "cases" not in await db.list_collection_names():
        await db.create_collection("cases")
    if "audit_log" not in await db.list_collection_names():
        await db.create_collection("audit_log")

    case_id = "CASE-SUCCESS-001"
    initial_doc = {"case_id": case_id, "status": "draft"}
    await cases_collection.insert_one(initial_doc)

    async def successful_transaction(session: AsyncIOMotorClientSession) -> dict[str, str]:
        # Step 1: Update case
        await cases_collection.update_one(
            {"case_id": case_id},
            {"$set": {"status": "submitted"}},
            session=session,
        )
        # Step 2: Write audit entry
        await audit_collection.insert_one(
            {
                "case_id": case_id,
                "action": "status_change",
                "from_status": "draft",
                "to_status": "submitted",
            },
            session=session,
        )
        return {"status": "committed"}

    result = await run_transaction(test_mongo_client, successful_transaction)
    assert result == {"status": "committed"}

    # Verify both writes were committed
    case_in_db = await cases_collection.find_one({"case_id": case_id})
    assert case_in_db is not None
    assert case_in_db["status"] == "submitted"

    audit_entry = await audit_collection.find_one({"case_id": case_id})
    assert audit_entry is not None
    assert audit_entry["to_status"] == "submitted"
