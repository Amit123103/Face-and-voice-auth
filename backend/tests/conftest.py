"""
Shared test fixtures for the FaceVoiceAuth test suite.
"""

import os
import base64

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_facevoiceauth.db"
os.environ["ASYNC_DATABASE_URL"] = "sqlite+aiosqlite:///./test_facevoiceauth.db"
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "a" * 64
os.environ["MASTER_KEY"] = base64.b64encode(b"k" * 32).decode()
os.environ["REDIS_URL"] = "memory://"
os.environ["BACKUP_DIR"] = "./test_backups"

import wave  # noqa: E402
import io  # noqa: E402
from typing import AsyncGenerator  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)  # noqa: E402

from backend.database import Base, get_db  # noqa: E402
from backend.main import app  # noqa: E402


test_engine = create_async_engine(
    "sqlite+aiosqlite:///./test_facevoiceauth.db",
    connect_args={"check_same_thread": False},
)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean database session for each test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client with overridden DB dependency."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def sample_user_data() -> dict:
    """Standard user registration payload."""
    return {
        "email": "test@example.com",
        "username": "testuser",
        "full_name": "Test User",
        "password": "SecureP@ssw0rd!123",
        "auth_mode": "password",
    }


@pytest.fixture
def admin_user_data() -> dict:
    """Admin user registration payload."""
    return {
        "email": "admin@test.com",
        "username": "adminuser",
        "full_name": "Admin User",
        "password": "AdminP@ssw0rd!456",
        "auth_mode": "password",
    }


@pytest.fixture
def fake_face_image_b64() -> str:
    """Generate a minimal valid base64 image for face testing."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[100:380, 200:440] = [200, 180, 160]
    import cv2
    _, buffer = cv2.imencode(".jpg", img)
    return base64.b64encode(buffer).decode("utf-8")


@pytest.fixture
def fake_voice_wav_b64() -> str:
    """Generate a minimal valid WAV audio blob for voice testing."""
    sample_rate = 16000
    duration = 4.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    tone = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    noise = np.random.randint(-500, 500, len(tone), dtype=np.int16)
    samples = tone + noise

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(samples.tobytes())

    return base64.b64encode(buffer.getvalue()).decode("utf-8")
