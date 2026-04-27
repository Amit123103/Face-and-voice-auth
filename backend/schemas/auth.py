"""
Auth Pydantic schemas — login, token, 2FA, and session schemas.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    totp_code: Optional[str] = Field(None, min_length=6, max_length=6)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    auth_method: str


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = None


class TOTPSetupResponse(BaseModel):
    secret: str
    qr_code_uri: str
    qr_code_base64: str
    backup_codes: List[str]


class TOTPVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class SessionResponse(BaseModel):
    id: str
    device_info: Optional[str] = None
    ip_address: Optional[str] = None
    auth_method: str
    created_at: datetime
    last_activity: datetime
    is_current: bool = False

    model_config = {"from_attributes": True}


class SessionListResponse(BaseModel):
    sessions: List[SessionResponse]
    total_count: int


class LockoutStatusResponse(BaseModel):
    is_locked: bool
    lockout_until: Optional[datetime] = None
    failed_attempts: int
    max_attempts: int
    remaining_seconds: Optional[int] = None
