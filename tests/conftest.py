import pytest
import pytest_asyncio
import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.models.database import Base, ServerEconomy, User
from src.services.database import DatabaseService

# Mock config loader to avoid reading file
@pytest.fixture(autouse=True)
def mock_config(monkeypatch):
    mock_conf = {
        "economy": {
            "starting_budget": 50000.0,
            "soldier_value": 10000.0,
            "tax_rate": 10.0
        },
        "roles": {},
        "channels": {},
        "salaries": {
            "soldier_per_10min": 10,
            "sergeant_per_10min": 20,
            "officer_per_10min": 20,
            "sergeant_master_bonus": 50
        }
    }

    # We mock load_config everywhere it might be used
    monkeypatch.setattr("src.utils.helpers.load_config", lambda: mock_conf)
    monkeypatch.setattr("src.services.database.load_config", lambda: mock_conf, raising=False)
    monkeypatch.setattr("src.cogs.admin.load_config", lambda: mock_conf, raising=False)

    return mock_conf

@pytest_asyncio.fixture(scope="function")
async def db_engine():
    # Use in-memory SQLite with StaticPool so multiple connections share the same memory db
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    """
    Yields a session for setup/verification.
    """
    session_maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_maker() as session:
        # Initialize default server economy
        economy = ServerEconomy(
            total_budget=50000.0,
            tax_rate=10.0,
            soldier_value=10000.0
        )
        session.add(economy)
        await session.commit()

        yield session

@pytest_asyncio.fixture(scope="function")
async def db_service(db_engine):
    """
    Provides a DatabaseService instance that uses the shared test engine.
    It creates NEW sessions for each request, allowing concurrency tests to work.
    """
    service = DatabaseService("sqlite+aiosqlite:///:memory:")
    # Override the engine and sessionmaker to use our shared test engine
    service.engine = db_engine
    service.async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    return service
