import pytest
import asyncio
from unittest.mock import MagicMock, patch
from src.models.database import TransactionType
from src.services.database import DatabaseService

@pytest.mark.asyncio
async def test_transfer_atomicity_failure_simulation(db_service, db_session):
    """
    Simulate a failure in the middle of a non-atomic transfer.
    This test demonstrates why we need a single atomic transaction.
    """
    sender = await db_service.get_or_create_user(4001)
    recipient = await db_service.get_or_create_user(4002)

    await db_service.update_user_balance(4001, 100.0, TransactionType.ADMIN_ADD)

    # Old way: 2 separate calls
    amount = 50.0

    # 1. Deduct from Sender
    success, _, _ = await db_service.update_user_balance(4001, -amount, TransactionType.TRANSFER_OUT)
    assert success is True

    # SIMULATE CRASH / ERROR HERE
    # If we stop here, Sender lost 50, Recipient got 0. Money burned.

    # Verify broken state
    # We must fetch a FRESH instance because db_service session is closed
    sender = await db_service.get_user(4001)
    recipient = await db_service.get_user(4002)

    assert sender.balance == 50.0
    assert recipient.balance == 0.0 # Should be +50 (minus tax) if successful, or +0 if failed safely

    # In a proper atomic transaction, if the second part fails, the first part (sender deduction)
    # should NOT be visible/committed.

@pytest.mark.asyncio
async def test_atomic_transfer_method(db_service, db_session):
    """
    Test the NEW atomic transfer method (to be implemented).
    """
    sender = await db_service.get_or_create_user(5001)
    recipient = await db_service.get_or_create_user(5002)
    economy = await db_service.get_server_economy()

    await db_service.update_user_balance(5001, 100.0, TransactionType.ADMIN_ADD)

    amount = 50.0
    # Expected tax
    net = amount * (1 - economy.tax_rate/100)
    tax = amount * (economy.tax_rate/100)

    # Call the new method (we will implement this next)
    # We expect this method to exist on db_service
    if not hasattr(db_service, 'transfer_money'):
        pytest.skip("transfer_money method not implemented yet")

    result = await db_service.transfer_money(
        sender_id=5001,
        recipient_id=5002,
        amount=amount,
        description="Atomic Transfer"
    )

    assert result["success"] is True
    assert result["tax"] == tax
    assert result["net_amount"] == net

    # Re-fetch fresh state
    sender = await db_service.get_user(5001)
    recipient = await db_service.get_user(5002)

    assert sender.balance == 50.0
    assert recipient.balance == net

@pytest.mark.asyncio
async def test_atomic_transfer_rollback(db_service, db_session):
    """
    Test that atomic transfer rolls back if something goes wrong internally.
    """
    if not hasattr(db_service, 'transfer_money'):
        pytest.skip("transfer_money method not implemented yet")

    sender = await db_service.get_or_create_user(6001)
    recipient = await db_service.get_or_create_user(6002)
    await db_service.update_user_balance(6001, 100.0, TransactionType.ADMIN_ADD)

    # Force an error by trying to transfer more than balance
    # The method should handle this gracefully return success=False
    # and balances should remain unchanged

    result = await db_service.transfer_money(
        sender_id=6001,
        recipient_id=6002,
        amount=200.0, # Too much
        description="Fail Transfer"
    )

    assert result["success"] is False

    sender = await db_service.get_user(6001)
    assert sender.balance == 100.0
