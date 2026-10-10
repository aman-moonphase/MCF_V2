import pytest
import asyncpg
import asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.core.config import settings

# Test DB URL
TEST_DATABASE_URL = settings.DATABASE_URL.replace("/mcf_db", "/mcf_db_test")
# The setup below drops all tables. Refuse to run against anything but a dedicated test database.
assert TEST_DATABASE_URL != settings.DATABASE_URL and TEST_DATABASE_URL.rstrip("/").endswith("_test"), (
    "Refusing to run tests: could not derive a separate *_test database from DATABASE_URL."
)

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=NullPool,
    echo=False
)

TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session", autouse=True)
async def setup_test_database():
    """Create the test database if it doesn't exist, and run migrations/create tables."""
    # Connect to the default postgres db to create the test db
    default_url = settings.DATABASE_URL.replace("/mcf_db", "/postgres")
    
    # We must replace postgresql+asyncpg:// with postgresql:// for asyncpg.connect
    asyncpg_url = default_url.replace("postgresql+asyncpg://", "postgresql://")
    
    try:
        conn = await asyncpg.connect(asyncpg_url)
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'mcf_db_test'")
        if not exists:
            await conn.execute("CREATE DATABASE mcf_db_test")
        await conn.close()
        
        # Create tables
        async with test_engine.begin() as conn:
            from sqlalchemy import text
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except ConnectionRefusedError:
        print("Warning: Could not connect to Postgres. DB tests may fail.")
        pass
    except OSError as e:
        if "WinError 1225" in str(e):
             print("Warning: Could not connect to Postgres (WinError 1225). DB tests may fail.")
             pass
        else:
             raise
    
    yield
    
    # Optionally drop tables after all tests, but leaving them is fine for inspection
    # async with test_engine.begin() as conn:
    #     await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()

@pytest.fixture(autouse=True)
def hermetic_ai_settings(monkeypatch):
    """Never call a real AI provider from tests.

    backend/.env may select a real provider (AI_PROVIDER=claude) and hold a real API key. Every test starts in
    Demo Mode with no provider keys and normal retry settings; tests that exercise Claude/OpenAI patch in fake
    clients or providers explicitly.
    """
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", None)
    monkeypatch.setattr(settings, "AI_SINGLE_ATTEMPT", False)

    # Belt and braces: a real Anthropic SDK HTTP request can never leave a test.
    import anthropic._base_client as anthropic_client

    async def no_real_requests(*args, **kwargs):
        raise AssertionError("A test attempted a real Anthropic API request.")

    monkeypatch.setattr(anthropic_client.AsyncAPIClient, "request", no_real_requests)


@pytest.fixture(autouse=True)
def smtp_outbox(monkeypatch):
    """Never send real email from tests.

    backend/.env may hold real SMTP credentials, and EmailService sends whenever they are set.
    The SMTP transport is replaced with an in-memory fake, so the full EmailService code path still
    runs and tests can inspect what would have been sent.
    """
    from app.services import email_service

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host, self.port = host, port

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, from_addr, to_addrs, msg):
            sent.append({"from": from_addr, "to": to_addrs, "message": msg})

        def quit(self):
            pass

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    return sent

@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fixture to provide a clean database session for a test."""
    async with TestingSessionLocal() as session:
        yield session
        # We can rollback any uncommitted transactions
        await session.rollback()

@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Fixture to provide an AsyncClient that overrides the get_db dependency."""
    
    async def override_get_db():
        yield db_session
        
    app.dependency_overrides[get_db] = override_get_db
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
        
    # Clear overrides after the test
    app.dependency_overrides.clear()

@pytest.fixture
async def test_user(db_session: AsyncSession):
    from app.models.user import User
    from app.core.security import get_password_hash
    
    # Check if exists
    from sqlalchemy.future import select
    result = await db_session.execute(select(User).where(User.email == "test@example.com"))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            email="test@example.com",
            hashed_password=get_password_hash("testpassword"),
            is_active=True
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    
    return user

@pytest.fixture
async def authenticated_client(client: AsyncClient, test_user) -> AsyncClient:
    from app.core.security import create_access_token
    from datetime import timedelta
    from app.core.config import settings
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=str(test_user.id), expires_delta=access_token_expires
    )
    
    client.headers.update({"Authorization": f"Bearer {access_token}"})
    return client
