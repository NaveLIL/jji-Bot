"""
Cleanup duplicate CaseUse records
Run this once to fix the database
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import select, delete, func
from src.services.database import db
from src.models.database import CaseUse


async def cleanup_duplicates():
    """Remove duplicate CaseUse records, keeping only the most recent one per user"""
    
    async with db.session() as session:
        # Get all user IDs with their case use counts
        result = await session.execute(
            select(CaseUse.user_id, func.count(CaseUse.id))
            .group_by(CaseUse.user_id)
            .having(func.count(CaseUse.id) > 1)
        )
        
        duplicates = result.all()
        
        if not duplicates:
            print("✅ No duplicates found!")
            return
        
        print(f"Found {len(duplicates)} users with duplicate records")
        
        total_deleted = 0
        for user_id, count in duplicates:
            # Get all records for this user, ordered by date
            records_result = await session.execute(
                select(CaseUse)
                .where(CaseUse.user_id == user_id)
                .order_by(CaseUse.last_used.desc())
            )
            records = list(records_result.scalars().all())
            
            # Keep the most recent, delete the rest
            to_keep = records[0]
            to_delete = records[1:]
            
            for record in to_delete:
                await session.delete(record)
                total_deleted += 1
            
            print(f"  User {user_id}: kept 1, deleted {len(to_delete)} records")
        
        await session.commit()
        print(f"\n✅ Cleanup complete! Deleted {total_deleted} duplicate records")


if __name__ == "__main__":
    print("Starting CaseUse cleanup...")
    asyncio.run(cleanup_duplicates())
