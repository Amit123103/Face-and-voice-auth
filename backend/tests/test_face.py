"""
Test suite for face recognition endpoints — enrollment, verification, liveness, encryption.
"""

import base64


import numpy as np
import pytest

from httpx import AsyncClient
from unittest.mock import patch


@pytest.mark.asyncio
async def test_enroll_face_success(client: AsyncClient, sample_user_data: dict, fake_face_image_b64: str):
    """Face enrollment with a valid image succeeds."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": sample_user_data["email"],
            "password": sample_user_data["password"],
        },
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with patch("backend.services.face_service.face_service.enroll_face") as mock_enroll:
        mock_enroll.return_value = ("encrypted_blob_b64", "nonce_b64", 0.85)
        response = await client.post(
            "/api/face/enroll",
            json={
                "angle": "front",
                "image_base64": fake_face_image_b64,
            },
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["angle"] == "front"
    assert data["quality_score"] >= 0.0
    assert "front" in data["enrolled_angles"]


@pytest.mark.asyncio
async def test_enroll_rejects_no_face(client: AsyncClient, sample_user_data: dict):
    """Enrollment rejects images with no detectable face."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": sample_user_data["email"],
            "password": sample_user_data["password"],
        },
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with patch("backend.services.face_service.face_service.enroll_face") as mock_enroll:
        mock_enroll.side_effect = ValueError("No face detected in the image")
        response = await client.post(
            "/api/face/enroll",
            json={
                "angle": "front",
                "image_base64": base64.b64encode(b"\x00" * 100).decode(),
            },
            headers=headers,
        )

    assert response.status_code == 400
    assert "no face" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_face_match_known_user(client: AsyncClient, sample_user_data: dict, fake_face_image_b64: str):
    """Face verification matches a known enrolled user."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": sample_user_data["email"],
            "password": sample_user_data["password"],
        },
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with patch("backend.services.face_service.face_service.enroll_face") as mock_enroll:
        mock_enroll.return_value = ("encrypted_blob_b64", "nonce_b64", 0.9)
        await client.post(
            "/api/face/enroll",
            json={
                "angle": "front",
                "image_base64": fake_face_image_b64,
            },
            headers=headers,
        )

    with patch("backend.services.face_service.face_service.verify_face") as mock_verify:
        mock_verify.return_value = (True, 0.92, 3)
        response = await client.post(
            f"/api/face/verify?email={sample_user_data['email']}",
            json={"frames": [fake_face_image_b64, fake_face_image_b64, fake_face_image_b64]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["confidence"] >= 0.8


@pytest.mark.asyncio
async def test_face_no_match_unknown(client: AsyncClient, sample_user_data: dict, fake_face_image_b64: str):
    """Face verification rejects an unknown face."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": sample_user_data["email"],
            "password": sample_user_data["password"],
        },
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with patch("backend.services.face_service.face_service.enroll_face") as mock_enroll:
        mock_enroll.return_value = ("encrypted_blob_b64", "nonce_b64", 0.9)
        await client.post(
            "/api/face/enroll",
            json={
                "angle": "front",
                "image_base64": fake_face_image_b64,
            },
            headers=headers,
        )

    with patch("backend.services.face_service.face_service.verify_face") as mock_verify:
        mock_verify.return_value = (False, 0.25, 0)
        response = await client.post(
            f"/api/face/verify?email={sample_user_data['email']}",
            json={"frames": [fake_face_image_b64]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is False


@pytest.mark.asyncio
async def test_liveness_blink_detected():
    """Blink detection correctly identifies blinks from EAR values."""
    from backend.services.face_liveness_service import face_liveness_service

    ear_values = [0.30, 0.28, 0.25, 0.15, 0.12, 0.10, 0.14, 0.25, 0.30, 0.28]
    detected, count = face_liveness_service.detect_blink(ear_values)
    assert detected is True
    assert count >= 1


@pytest.mark.asyncio
async def test_liveness_static_image_rejected():
    """Static image (no blinks) fails liveness check."""
    from backend.services.face_liveness_service import face_liveness_service

    ear_values = [0.30] * 30
    detected, count = face_liveness_service.detect_blink(ear_values)
    assert detected is False
    assert count == 0


@pytest.mark.asyncio
async def test_encryption_roundtrip():
    """Encrypting and decrypting biometric data preserves the original."""
    from backend.services.encryption_service import encryption_service

    user_id = "test-user-123"
    salt = encryption_service.generate_salt()

    original = np.random.randn(128).astype(np.float64)
    original_bytes = original.tobytes()

    encrypted_b64, nonce_b64 = encryption_service.encrypt(original_bytes, user_id, salt)

    decrypted_bytes = encryption_service.decrypt(encrypted_b64, nonce_b64, user_id, salt)

    recovered = np.frombuffer(decrypted_bytes, dtype=np.float64)
    np.testing.assert_array_almost_equal(original, recovered)


@pytest.mark.asyncio
async def test_face_status_endpoint(client: AsyncClient, sample_user_data: dict):
    """Face status endpoint returns enrollment details."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": sample_user_data["email"],
            "password": sample_user_data["password"],
        },
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.get("/api/face/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["enrolled"] is False
    assert data["enrolled_angles"] == []
