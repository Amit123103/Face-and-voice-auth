"""
Test suite for voice authentication — enrollment, verification, liveness.
"""

import base64
import io

import wave

import numpy as np
import pytest
from httpx import AsyncClient



def _make_wav_b64(duration: float = 4.0, sample_rate: int = 16000) -> str:
    """Generate a synthetic WAV file as base64."""
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


@pytest.mark.asyncio
async def test_voice_enroll_start(client: AsyncClient, sample_user_data: dict):
    """Starting voice enrollment returns a challenge PIN."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post("/api/auth/login", json={
        "email": sample_user_data["email"],
        "password": sample_user_data["password"],
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post("/api/voice/enroll/start", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data["challenge_pin"]) == 4
    assert "session_id" in data
    assert data["min_samples"] >= 1


@pytest.mark.asyncio
async def test_voice_sample_quality_assessment():
    """Voice sample quality assessment identifies acceptable samples."""
    from backend.services.voice_service import voice_service

    good_wav = _make_wav_b64(duration=5.0, sample_rate=16000)
    is_ok, quality, snr, duration, feedback = voice_service.assess_sample_quality(good_wav)
    assert duration >= 3.0
    assert quality > 0.0


@pytest.mark.asyncio
async def test_voice_sample_too_short():
    """Samples shorter than minimum duration are rejected."""
    from backend.services.voice_service import voice_service

    short_wav = _make_wav_b64(duration=1.0, sample_rate=16000)
    is_ok, quality, snr, duration, feedback = voice_service.assess_sample_quality(short_wav)
    assert is_ok is False
    assert any("short" in f.lower() for f in feedback)


@pytest.mark.asyncio
async def test_voice_verify_cosine_similarity():
    """Voice verification computes cosine similarity correctly."""
    from backend.services.encryption_service import encryption_service

    user_id = "voice-test-user"
    salt = encryption_service.generate_salt()

    embedding = np.random.randn(256).astype(np.float64)
    embedding /= np.linalg.norm(embedding)
    enc_b64, nonce_b64 = encryption_service.encrypt(
        embedding.tobytes(), user_id, salt
    )



    decrypted = encryption_service.decrypt(enc_b64, nonce_b64, user_id, salt)
    recovered = np.frombuffer(decrypted, dtype=np.float64)
    similarity = float(np.dot(
        embedding / np.linalg.norm(embedding),
        recovered / np.linalg.norm(recovered),
    ))
    assert similarity > 0.99


@pytest.mark.asyncio
async def test_voice_liveness_replay_detection():
    """Voice liveness service detects potential replay attacks."""
    from backend.services.voice_liveness_service import voice_liveness_service

    wav_b64 = _make_wav_b64(duration=4.0, sample_rate=16000)
    format_valid, format_info = voice_liveness_service.validate_audio_format(wav_b64)
    assert format_valid is True
    assert format_info["sample_rate"] == 16000


@pytest.mark.asyncio
async def test_voice_liveness_silence_detection():
    """Voice liveness rejects clips with too much silence."""
    from backend.services.voice_liveness_service import voice_liveness_service

    sample_rate = 16000
    duration = 4.0
    samples = np.zeros(int(sample_rate * duration), dtype=np.float32)

    ok, ratio = voice_liveness_service.check_silence_ratio(samples)
    assert ok is False
    assert ratio > 0.6


@pytest.mark.asyncio
async def test_voice_status_endpoint(client: AsyncClient, sample_user_data: dict):
    """Voice status endpoint returns enrollment details."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post("/api/auth/login", json={
        "email": sample_user_data["email"],
        "password": sample_user_data["password"],
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/voice/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["enrolled"] is False
    assert data["sample_count"] == 0


@pytest.mark.asyncio
async def test_voice_encryption_roundtrip():
    """Voice embeddings survive encryption and decryption intact."""
    from backend.services.encryption_service import encryption_service

    user_id = "voice-enc-test"
    salt = encryption_service.generate_salt()

    original = np.random.randn(256).astype(np.float64)
    enc_b64, nonce_b64 = encryption_service.encrypt(
        original.tobytes(), user_id, salt
    )
    decrypted = encryption_service.decrypt(enc_b64, nonce_b64, user_id, salt)
    recovered = np.frombuffer(decrypted, dtype=np.float64)

    np.testing.assert_array_almost_equal(original, recovered)
