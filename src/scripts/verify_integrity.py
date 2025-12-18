import asyncio
import os
import sys

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import select, func, text
from src.services.database import db, DatabaseService
from src.models.database import User, ServerEconomy, Transaction

async def verify_integrity():
    print("🔍 Starting Database Integrity Check...")

    # We need to create a new service connected to the actual DB if we were running against production
    # But here we will check the current dev DB or whatever is configured

    async with db.session() as session:
        # 1. Check for negative balances (should be caught by Constraint, but verify)
        print("\n1. Checking for negative balances...")
        result = await session.execute(
            select(User).where(User.balance < 0)
        )
        neg_users = result.scalars().all()
        if neg_users:
            print(f"❌ FOUND {len(neg_users)} USERS WITH NEGATIVE BALANCE!")
            for u in neg_users:
                print(f"   - User ID: {u.id}, Balance: {u.balance}")
        else:
            print("✅ No negative balances found.")

        # 2. Check Total Money Supply
        print("\n2. Analyzing Money Supply...")
        user_balance_sum = (await session.execute(select(func.sum(User.balance)))).scalar() or 0

        economy = (await session.execute(select(ServerEconomy))).scalar_one_or_none()
        if not economy:
            print("❌ Server Economy record missing!")
            return

        server_budget = economy.total_budget

        print(f"   - Total User Balance: {user_balance_sum:,.2f}")
        print(f"   - Server Budget:      {server_budget:,.2f}")
        print(f"   - TOTAL SUPPLY:       {user_balance_sum + server_budget:,.2f}")

        # 3. Orphaned Transactions
        print("\n3. Checking for orphaned transactions...")
        result = await session.execute(
            select(func.count(Transaction.id)).where(Transaction.user_id.not_in(select(User.id)))
        )
        orphaned_tx = result.scalar()
        if orphaned_tx > 0:
            print(f"❌ Found {orphaned_tx} orphaned transactions!")
        else:
            print("✅ No orphaned transactions found.")

        # 4. Check Tax Consistency (Heuristic)
        # Check if total_taxes_collected is roughly consistent with transaction history
        # (This is hard to do exactly without replay, but we can check if it's > 0 if transactions exist)
        print("\n4. Checking Tax Stats...")
        if economy.total_taxes_collected < 0:
             print(f"❌ Total taxes collected is negative: {economy.total_taxes_collected}")
        else:
             print(f"✅ Taxes collected seems valid: {economy.total_taxes_collected:,.2f}")

if __name__ == "__main__":
    asyncio.run(verify_integrity())
