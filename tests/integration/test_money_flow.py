import pytest
from src.models.database import User, TransactionType, ServerEconomy, Role, RoleType
from src.utils.helpers import calculate_tax

@pytest.mark.asyncio
async def test_p2p_transfer_conservation(db_service, db_session):
    """
    Test that Peer-to-Peer transfers conserve total money (User + Server).
    Flow: User A -> User B (Tax -> Server)
    """
    # Setup users
    user_a = await db_service.get_or_create_user(1001)
    user_b = await db_service.get_or_create_user(1002)

    # Give initial money
    await db_service.update_user_balance(1001, 1000.0, TransactionType.ADMIN_ADD)
    await db_service.update_user_balance(1002, 500.0, TransactionType.ADMIN_ADD)

    # Refresh users in db_session to get current state (because db_service used a different session)
    user_a = await db_session.get(User, user_a.id)
    user_b = await db_session.get(User, user_b.id)
    economy = await db_service.get_server_economy()
    economy = await db_session.get(ServerEconomy, economy.id)

    initial_budget = economy.total_budget
    initial_user_supply = user_a.balance + user_b.balance
    initial_total_money = initial_budget + initial_user_supply

    # Perform Transfer: 100 from A to B
    transfer_amount = 100.0
    tax_rate = economy.tax_rate
    net_amount, tax_amount = calculate_tax(transfer_amount, tax_rate)

    # Use Atomic Transfer
    await db_service.transfer_money(1001, 1002, transfer_amount)

    # Verify State
    await db_session.refresh(user_a)
    await db_session.refresh(user_b)
    await db_session.refresh(economy)

    final_user_supply = user_a.balance + user_b.balance
    final_budget = economy.total_budget
    final_total_money = final_budget + final_user_supply

    # Assertions
    assert user_a.balance == 1000.0 - transfer_amount
    assert user_b.balance == 500.0 + net_amount
    assert final_budget == initial_budget + tax_amount

    # Floating point comparison
    assert abs(final_total_money - initial_total_money) < 0.001

@pytest.mark.asyncio
async def test_gambling_flow(db_service, db_session):
    """
    Test Gambling Flow (Win/Loss)
    """
    user = await db_service.get_or_create_user(2001)
    await db_service.update_user_balance(2001, 1000.0, TransactionType.ADMIN_ADD)

    # Refresh user
    user = await db_session.get(User, user.id)
    economy = await db_service.get_server_economy()
    economy = await db_session.get(ServerEconomy, economy.id)

    initial_budget = economy.total_budget
    bet_amount = 100.0

    # --- Scenario 1: User Bets (Money moves to System) ---
    await db_service.update_user_balance(2001, -bet_amount, TransactionType.GAME_LOSS)
    await db_service.update_server_budget(bet_amount, add=True)

    await db_session.refresh(user)
    await db_session.refresh(economy)

    assert user.balance == 900.0
    assert economy.total_budget == initial_budget + bet_amount

    # --- Scenario 2: User Wins (Money moves back + Profit) ---
    payout = 200.0 # 2x multiplier

    # Payout comes from budget
    await db_service.update_server_budget(payout, add=False) # Deduct
    await db_service.update_user_balance(2001, payout, TransactionType.GAME_WIN)

    await db_session.refresh(user)
    await db_session.refresh(economy)

    # Net result: User +100, Budget -100
    assert user.balance == 1100.0
    assert economy.total_budget == initial_budget - 100.0

@pytest.mark.asyncio
async def test_shop_purchase_flow(db_service, db_session):
    """
    Test Role Shop Purchase
    """
    user = await db_service.get_or_create_user(3001)
    await db_service.update_user_balance(3001, 1000.0, TransactionType.ADMIN_ADD)

    user = await db_session.get(User, user.id)

    # Add a role to shop
    await db_service.add_shop_role(
        discord_id=999, name="Test Role", role_type=RoleType.COLOR, price=100.0
    )

    economy = await db_service.get_server_economy()
    economy = await db_session.get(ServerEconomy, economy.id)
    initial_budget = economy.total_budget

    # User buys role
    success, msg = await db_service.purchase_role(3001, 999)

    assert success is True

    await db_session.refresh(user)
    await db_session.refresh(economy)

    # Role price is 100. Money should move User -> Budget
    assert user.balance == 900.0
    assert economy.total_budget == initial_budget + 100.0
