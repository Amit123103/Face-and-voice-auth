"""
Auth Router — password login, registration, JWT refresh, TOTP, and session management.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.rate_limiter import limiter
from backend.schemas.auth import (
    LoginRequest,
    TokenResponse,
    TOTPSetupResponse,
    TOTPVerifyRequest,
    SessionListResponse,
    SessionResponse,
    LockoutStatusResponse,
)
from backend.schemas.user import UserCreate, UserResponse, PasswordStrengthResponse
from backend.services.auth_service import auth_service
from backend.services.email_service import email_service
from backend.models.user import User
from backend.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["Authentication"])


async def get_current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Dependency to extract and validate the current authenticated user."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = auth_header.split(" ", 1)[1]
    payload = auth_service.decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await auth_service.get_user_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    request.state.user_id = user.id
    return user


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    data: UserCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user account."""
    try:
        user = await auth_service.register_user(
            db, data.email, data.username, data.full_name,
            data.password, data.auth_mode,
        )
        background_tasks.add_task(email_service.send_welcome_email, user.email, user.full_name)
        return UserResponse.model_validate(user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with email and password. Returns JWT access token."""
    user = await auth_service.authenticate_password(db, data.email, data.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials or account locked",
        )

    if user.totp_enabled:
        if not data.totp_code:
            raise HTTPException(
                status_code=403,
                detail="2FA code required",
            )
        if not auth_service.verify_totp(user.totp_secret, data.totp_code):
            raise HTTPException(status_code=403, detail="Invalid 2FA code")

    access_token, expires_in = auth_service.create_access_token(
        user.id, user.role.value, "password"
    )
    refresh_token, _ = auth_service.create_refresh_token()

    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    await auth_service.create_session(
        db, user, refresh_token, client_ip, user_agent, "password"
    )

    background_tasks.add_task(email_service.send_login_alert, user.email, client_ip, "Password")

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        max_age=7 * 24 * 3600,
        path="/api/auth/refresh",
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user_id=user.id,
        auth_method="password",
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Refresh the JWT access token using the refresh token cookie."""
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token provided")

    result = await auth_service.refresh_access_token(db, token)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    access_token, expires_in, user_id = result

    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        user_id=user_id,
        auth_method="refresh",
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Logout: revoke current session and clear refresh token cookie."""
    refresh_token_val = request.cookies.get("refresh_token")
    if refresh_token_val:
        token_hash = auth_service.hash_refresh_token(refresh_token_val)
        from sqlalchemy import select, and_
        from backend.models.session import SessionRecord

        result = await db.execute(
            select(SessionRecord).where(
                and_(
                    SessionRecord.refresh_token_hash == token_hash,
                    SessionRecord.user_id == current_user.id,
                )
            )
        )
        session = result.scalar_one_or_none()
        if session:
            await auth_service.revoke_session(db, session.id)

    response.delete_cookie("refresh_token", path="/api/auth/refresh")
    return {"message": "Logged out successfully"}


@router.post("/totp/setup", response_model=TOTPSetupResponse)
async def setup_totp(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Initialize TOTP-based 2FA for the current user."""
    secret = auth_service.generate_totp_secret()
    uri = auth_service.get_totp_uri(secret, current_user.email)
    qr_base64 = auth_service.generate_qr_base64(uri)
    backup_codes = auth_service.generate_backup_codes()

    current_user.totp_secret = secret
    current_user.backup_codes = ",".join(backup_codes)
    await db.flush()

    return TOTPSetupResponse(
        secret=secret,
        qr_code_uri=uri,
        qr_code_base64=qr_base64,
        backup_codes=backup_codes,
    )


@router.post("/totp/verify")
async def verify_totp(
    data: TOTPVerifyRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verify TOTP code and enable 2FA for the user."""
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="TOTP not set up yet")

    if not auth_service.verify_totp(current_user.totp_secret, data.code):
        raise HTTPException(status_code=403, detail="Invalid TOTP code")

    current_user.totp_enabled = True
    current_user.security_score = current_user.compute_security_score()
    await db.flush()

    background_tasks.add_task(
        email_service.send_security_alert, 
        current_user.email, 
        "2FA Enabled", 
        "TOTP-based two-factor authentication has been successfully enabled on your account."
    )

    return {"message": "2FA enabled successfully"}


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all active sessions for the current user."""
    sessions = await auth_service.get_user_sessions(db, current_user.id)
    return SessionListResponse(
        sessions=[SessionResponse.model_validate(s) for s in sessions],
        total_count=len(sessions),
    )


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke a specific session."""
    success = await auth_service.revoke_session(db, session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Session revoked"}


@router.delete("/sessions")
async def revoke_all_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke all other sessions except the current one."""
    count = await auth_service.revoke_all_sessions(db, current_user.id)
    return {"message": f"Revoked {count} sessions"}


@router.get("/me", response_model=UserResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Get the current user's profile."""
    return UserResponse.model_validate(current_user)


@router.post("/password-strength", response_model=PasswordStrengthResponse)
async def check_password_strength(data: dict):
    """Check password strength and return feedback."""
    password = data.get("password", "")
    result = auth_service.check_password_strength(password)
    return PasswordStrengthResponse(**result)
