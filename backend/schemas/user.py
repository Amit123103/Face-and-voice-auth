"""
User Pydantic schemas — request/response validation models.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_]+$")
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    auth_mode: str = Field(default="password")


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    auth_mode: Optional[str] = None
    fallback_allowed: Optional[bool] = None


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: str
    role: str
    auth_mode: str
    fallback_allowed: bool
    is_active: bool
    is_verified: bool
    face_enrolled: bool
    voice_enrolled: bool
    totp_enabled: bool
    security_score: float
    last_login_at: Optional[datetime] = None
    last_login_method: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    users: List[UserResponse]
    next_cursor: Optional[str] = None
    total_count: int


class PasswordStrengthResponse(BaseModel):
    score: int = Field(..., ge=0, le=4)
    feedback: List[str]
    crack_time: str
    is_strong: bool
