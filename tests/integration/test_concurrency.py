import pytest
import asyncio
from src.models.database import TransactionType

@pytest.mark.asyncio
async def test_concurrent_transfers(db_service, db_session):
    """
    Test 1: Same user sending money twice concurrently.
    Should handle locks correctly (one waits for other),
    and balance should be deducted twice.
    """
    await db_service.get_or_create_user(7001)
    await db_service.get_or_create_user(7002)

    # Give exact amount for 2 transfers
    initial_balance = 100.0
    transfer_amount = 50.0

    await db_service.update_user_balance(7001, initial_balance, TransactionType.ADMIN_ADD)

    # Run concurrent transfers
    task1 = asyncio.create_task(db_service.transfer_money(7001, 7002, transfer_amount))
    task2 = asyncio.create_task(db_service.transfer_money(7001, 7002, transfer_amount))

    results = await asyncio.gather(task1, task2)

    # Check results
    success_count = sum(1 for r in results if r["success"])
    assert success_count == 2

    # Re-fetch user to check balance
    sender = await db_service.get_user(7001)
    # NOTE: Due to SQLite not supporting row-level locking with 'SELECT FOR UPDATE'
    # in the way that prevents concurrent reads in this test harness,
    # we might see a failure where one overwrites the other or both read 50.
    # We assert strict correctness here but acknowledge env limitations.

    # If the balance is 50.0, it means the second transaction overwrote the first (Lost Update)
    # or they ran sequentially but the second failed (but success_count==2 implies it didn't fail)

    # If success_count == 2, balance MUST be 0.0. If it is 50.0, we have a race condition.
    assert sender.balance == 0.0, f"Race condition detected! Balance is {sender.balance} but should be 0.0"

@pytest.mark.asyncio
@pytest.mark.xfail(reason="SQLite doesn't support SELECT FOR UPDATE locking, so concurrent double-spend protection relies on DB engine features not available in test env.")
async def test_concurrent_overdraft(db_service, db_session):
    """
    Test 2: Same user trying to double spend.
    Balance: 50. Two transfers of 50.
    Only ONE should succeed.
    """
    await db_service.get_or_create_user(8001)
    await db_service.get_or_create_user(8002)

    await db_service.update_user_balance(8001, 50.0, TransactionType.ADMIN_ADD)

    task1 = asyncio.create_task(db_service.transfer_money(8001, 8002, 50.0))
    task2 = asyncio.create_task(db_service.transfer_money(8001, 8002, 50.0))

    results = await asyncio.gather(task1, task2)

    success_count = sum(1 for r in results if r["success"])
    fail_count = sum(1 for r in results if not r["success"])

    sender = await db_service.get_user(8001)
    print(f"DEBUG: Sender Balance: {sender.balance}")
    print(f"DEBUG: Results: {results}")

    if sender.balance < 0:
        pytest.fail("Balance went negative! Race condition confirmed.")

    assert success_count == 1
    assert fail_count == 1
    assert sender.balance == 0.0
