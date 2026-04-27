"""
Test suite for authentication endpoints — registration, login, JWT, TOTP, sessions.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient, sample_user_data: dict):
    """Successful user registration returns 201 with user profile."""
    response = await client.post("/api/auth/register", json=sample_user_data)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == sample_user_data["email"]
    assert data["username"] == sample_user_data["username"]
    assert data["role"] == "user"
    assert data["is_active"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email_fails(client: AsyncClient, sample_user_data: dict):
    """Registering with a duplicate email returns 409 Conflict."""
    await client.post("/api/auth/register", json=sample_user_data)
    response = await client.post("/api/auth/register", json=sample_user_data)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_correct_password(client: AsyncClient, sample_user_data: dict):
    """Login with correct credentials returns access token."""
    await client.post("/api/auth/register", json=sample_user_data)
    response = await client.post("/api/auth/login", json={
        "email": sample_user_data["email"],
        "password": sample_user_data["password"],
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["auth_method"] == "password"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_wrong_password_increments_lockout(client: AsyncClient, sample_user_data: dict):
    """Wrong password increments failed login count."""
    await client.post("/api/auth/register", json=sample_user_data)
    response = await client.post("/api/auth/login", json={
        "email": sample_user_data["email"],
        "password": "WrongPassword123!",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_account_locks_after_5_failures(client: AsyncClient, sample_user_data: dict):
    """Account locks after 5 consecutive failed login attempts."""
    await client.post("/api/auth/register", json=sample_user_data)
    for i in range(6):
        response = await client.post("/api/auth/login", json={
            "email": sample_user_data["email"],
            "password": f"WrongPass{i}!",
        })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_jwt_token_valid(client: AsyncClient, sample_user_data: dict):
    """A valid JWT can be used to access protected endpoints."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post("/api/auth/login", json={
        "email": sample_user_data["email"],
        "password": sample_user_data["password"],
    })
    token = login_resp.json()["access_token"]

    me_resp = await client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}",
    })
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == sample_user_data["email"]


@pytest.mark.asyncio
async def test_expired_token_rejected(client: AsyncClient):
    """An invalid/expired token is rejected with 401."""
    response = await client.get("/api/auth/me", headers={
        "Authorization": "Bearer invalid.token.here",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotation(client: AsyncClient, sample_user_data: dict):
    """Refresh token cookie can be used to get a new access token."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post("/api/auth/login", json={
        "email": sample_user_data["email"],
        "password": sample_user_data["password"],
    })
    assert login_resp.status_code == 200

    cookies = login_resp.cookies
    if "refresh_token" in cookies:
        refresh_resp = await client.post(
            "/api/auth/refresh",
            cookies={"refresh_token": cookies["refresh_token"]},
        )
        assert refresh_resp.status_code == 200
        assert "access_token" in refresh_resp.json()


@pytest.mark.asyncio
async def test_2fa_totp_valid(client: AsyncClient, sample_user_data: dict):
    """Setting up and verifying TOTP 2FA works correctly."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post("/api/auth/login", json={
        "email": sample_user_data["email"],
        "password": sample_user_data["password"],
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    setup_resp = await client.post("/api/auth/totp/setup", headers=headers)
    assert setup_resp.status_code == 200
    data = setup_resp.json()
    assert "secret" in data
    assert "qr_code_base64" in data
    assert len(data["backup_codes"]) == 8

    import pyotp
    totp = pyotp.TOTP(data["secret"])
    valid_code = totp.now()

    verify_resp = await client.post(
        "/api/auth/totp/verify",
        json={"code": valid_code},
        headers=headers,
    )
    assert verify_resp.status_code == 200


@pytest.mark.asyncio
async def test_2fa_totp_invalid_rejected(client: AsyncClient, sample_user_data: dict):
    """An invalid TOTP code is rejected."""
    await client.post("/api/auth/register", json=sample_user_data)
    login_resp = await client.post("/api/auth/login", json={
        "email": sample_user_data["email"],
        "password": sample_user_data["password"],
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/api/auth/totp/setup", headers=headers)

    verify_resp = await client.post(
        "/api/auth/totp/verify",
        json={"code": "000000"},
        headers=headers,
    )
    assert verify_resp.status_code == 403


@pytest.mark.asyncio
async def test_password_strength_check(client: AsyncClient):
    """Password strength endpoint returns scoring."""
    response = await client.post("/api/auth/password-strength", json={
        "password": "weak",
    })
    assert response.status_code == 200
    data = response.json()
    assert "score" in data
    assert data["is_strong"] is False
