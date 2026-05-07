"""
Account Security Router — Settings, activity logs, and 2FA management.
"""

from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.database import get_db
from backend.models.user import User
from backend.models.audit_log import AuditLog
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/api/account", tags=["Account Settings"])


class ActivityLogResponse(BaseModel):
    id: str
    action: str
    ip_address: str
    user_agent: str
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/activity", response_model=List[ActivityLogResponse])
async def get_activity_logs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve recent login activity for the user."""
    result = await db.execute(
        select(AuditLog).where(AuditLog.user_id == current_user.id).order_by(AuditLog.created_at.desc()).limit(20)
    )
    return result.scalars().all()


@router.get("/sessions")
async def get_sessions(
    current_user: User = Depends(get_current_user),
):
    """Placeholder for connected devices (sessions)."""
    # In a full implementation, this would query a Session model.
    # For now, we return a mock based on last login info.
    return [
        {
            "device": "Current Browser",
            "ip": current_user.last_login_ip or "Unknown",
            "last_active": current_user.last_login_at,
        }
    ]
