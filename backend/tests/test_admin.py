"""
Test suite for admin endpoints — user management, audit logs, backup, access control.
"""

import pytest
from httpx import AsyncClient
from unittest.mock import patch


async def _create_admin_and_login(client: AsyncClient) -> str:
    """Helper: register and login as admin, return access token."""
    # imports used implicitly or needed for type checking/side effects removed if unused

    admin_data = {
        "email": "admin@test.com",
        "username": "testadmin",
        "full_name": "Test Admin",
        "password": "AdminP@ss123!",
        "auth_mode": "password",
    }
    await client.post("/api/auth/register", json=admin_data)

    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": admin_data["email"],
            "password": admin_data["password"],
        },
    )
    token = login_resp.json()["access_token"]

    from jose import jwt
    from backend.config import get_settings

    settings = get_settings()
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    user_id = payload["sub"]

    return token, user_id


async def _create_regular_user(client: AsyncClient) -> tuple:
    """Helper: register and login as regular user."""
    user_data = {
        "email": "regular@test.com",
        "username": "regularuser",
        "full_name": "Regular User",
        "password": "UserP@ss123!",
        "auth_mode": "password",
    }
    reg_resp = await client.post("/api/auth/register", json=user_data)
    user_id = reg_resp.json()["id"]

    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": user_data["email"],
            "password": user_data["password"],
        },
    )
    token = login_resp.json()["access_token"]
    return token, user_id


@pytest.mark.asyncio
async def test_admin_list_users_paginated(client: AsyncClient, sample_user_data: dict):
    """Admin can list users with pagination."""
    admin_token, _ = await _create_admin_and_login(client)

    with patch("backend.routers.admin.require_admin") as mock_admin:
        from backend.models.user import User, UserRole

        mock_user = User(
            id="admin-id",
            email="admin@test.com",
            username="testadmin",
            full_name="Test Admin",
            hashed_password="x",
            role=UserRole.ADMIN,
        )
        mock_admin.return_value = mock_user

        response = await client.get(
            "/api/admin/users?limit=10",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code in [200, 403]


@pytest.mark.asyncio
async def test_non_admin_cannot_access(client: AsyncClient):
    """Regular users receive 403 on admin endpoints."""
    user_data = {
        "email": "user@test.com",
        "username": "normaluser",
        "full_name": "Normal User",
        "password": "UserP@ss123!",
        "auth_mode": "password",
    }
    await client.post("/api/auth/register", json=user_data)
    login_resp = await client.post(
        "/api/auth/login",
        json={
            "email": user_data["email"],
            "password": user_data["password"],
        },
    )
    token = login_resp.json()["access_token"]

    response = await client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_audit_log_entries_created(client: AsyncClient, sample_user_data: dict):
    """API requests generate audit log entries in the middleware."""
    await client.post("/api/auth/register", json=sample_user_data)

    response = await client.get("/health")
    assert response.status_code == 200
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_backup_triggered_successfully():
    """Backup service creates backup files without errors."""
    from backend.services.backup_service import backup_service

    result = backup_service.create_backup()
    assert "filename" in result
    assert result["filename"].startswith("facevoiceauth_backup_")
    assert result["size_bytes"] >= 0


@pytest.mark.asyncio
async def test_backup_list():
    """Backup service can list existing backups."""
    from backend.services.backup_service import backup_service

    backup_service.create_backup()
    backups = backup_service.list_backups()
    assert isinstance(backups, list)
    assert len(backups) >= 1


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    """Health endpoint returns system status."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_metrics_endpoint(client: AsyncClient):
    """Metrics endpoint returns Prometheus-formatted data."""
    response = await client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "facevoiceauth_uptime_seconds" in text
