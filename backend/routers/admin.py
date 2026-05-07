"""
Admin Router — user management, audit logs, system health, and backup controls.
Requires ADMIN role for all endpoints.
"""

import platform
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User, UserRole
from backend.models.session import SessionRecord
from backend.models.audit_log import AuditLog
from backend.models.voice_print import VoicePrint
from backend.models.face_encoding import FaceEncoding
from backend.models.transaction import Transaction, TransactionStatus
from backend.routers.auth import get_current_user
from backend.schemas.user import UserResponse, UserListResponse
from backend.schemas.transaction import TransactionResponse
from backend.services.auth_service import auth_service
from backend.services.backup_service import backup_service
from backend.services.face_service import face_service
from backend.services.voice_service import voice_service
from backend.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/admin", tags=["Admin"])


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency ensuring only admins can access admin endpoints."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@router.get("/users", response_model=UserListResponse)
async def list_users(
    cursor: str = Query(None, description="Cursor for pagination (user ID)"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """List all users with cursor-based pagination."""
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.created_at.desc())

    if cursor:
        cursor_user = await db.execute(select(User).where(User.id == cursor))
        cu = cursor_user.scalar_one_or_none()
        if cu:
            stmt = stmt.where(User.created_at < cu.created_at)

    stmt = stmt.limit(limit + 1)
    result = await db.execute(stmt)
    users = list(result.scalars().all())

    next_cursor = None
    if len(users) > limit:
        next_cursor = users[limit - 1].id
        users = users[:limit]

    count_result = await db.execute(select(func.count(User.id)).where(User.deleted_at.is_(None)))
    total = count_result.scalar()

    return UserListResponse(
        users=[UserResponse.model_validate(u) for u in users],
        next_cursor=next_cursor,
        total_count=total,
    )


@router.get("/users/{user_id}/audit")
async def get_user_audit_log(
    user_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """View full audit log for a specific user."""
    result = await db.execute(
        select(AuditLog).where(AuditLog.user_id == user_id).order_by(desc(AuditLog.created_at)).limit(limit)
    )
    logs = result.scalars().all()
    return {
        "user_id": user_id,
        "entries": [
            {
                "id": log.id,
                "action": log.action,
                "resource": log.resource,
                "detail": log.detail,
                "ip_address": log.ip_address,
                "method": log.method,
                "path": log.path,
                "status_code": log.status_code,
                "duration_ms": log.duration_ms,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total_returned": len(logs),
    }


@router.post("/users/{user_id}/revoke-sessions")
async def revoke_user_sessions(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Force-revoke all sessions for a specific user."""
    count = await auth_service.revoke_all_sessions(db, user_id)
    return {"message": f"Revoked {count} sessions for user {user_id}"}


@router.delete("/users/{user_id}")
async def soft_delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Soft-delete a user and revoke all their sessions."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user.deleted_at = datetime.utcnow()
    user.is_active = False
    await auth_service.revoke_all_sessions(db, user_id)
    await db.flush()

    return {"message": f"User {user_id} soft-deleted and sessions revoked"}


@router.post("/backup")
async def trigger_backup(admin: User = Depends(require_admin)):
    """Trigger a manual database backup."""
    result = backup_service.create_backup()
    return {"message": "Backup triggered", **result}


@router.get("/backups")
async def list_backups(admin: User = Depends(require_admin)):
    """List all available backups."""
    return {"backups": backup_service.list_backups()}


@router.get("/health")
async def system_health(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Detailed system health including biometric model status."""
    try:
        await db.execute(select(func.count(User.id)))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)

    active_sessions = await db.execute(
        select(func.count(SessionRecord.id)).where(
            and_(SessionRecord.is_active.is_(True), SessionRecord.revoked_at.is_(None))
        )
    )
    total_users = await db.execute(select(func.count(User.id)).where(User.deleted_at.is_(None)))

    failed_logins = await db.execute(
        select(func.count(AuditLog.id)).where(
            and_(
                AuditLog.action == "login_failed",
                AuditLog.created_at >= day_ago,
            )
        )
    )

    try:
        import psutil

        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
    except ImportError:
        cpu_percent = -1
        memory_percent = -1

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status,
        "face_model_loaded": face_service.is_ready,
        "voice_model_loaded": voice_service.is_ready,
        "system": {
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "stats": {
            "active_sessions": active_sessions.scalar() or 0,
            "total_users": total_users.scalar() or 0,
            "failed_logins_24h": failed_logins.scalar() or 0,
        },
        "version": settings.APP_VERSION,
        "timestamp": now.isoformat(),
    }


@router.get("/users/{user_id}/biometric-stats")
async def user_biometric_stats(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """View per-user biometric authentication stats."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    face_result = await db.execute(
        select(FaceEncoding).where(and_(FaceEncoding.user_id == user_id, FaceEncoding.is_active.is_(True)))
    )
    face_encodings = face_result.scalars().all()

    voice_result = await db.execute(
        select(VoicePrint).where(and_(VoicePrint.user_id == user_id, VoicePrint.is_active.is_(True)))
    )
    voice_prints = voice_result.scalars().all()

    return {
        "user_id": user_id,
        "face": {
            "enrolled": user.face_enrolled,
            "encoding_count": len(face_encodings),
            "angles": [e.angle_label for e in face_encodings],
            "total_matches": sum(e.match_count for e in face_encodings),
        },
        "voice": {
            "enrolled": user.voice_enrolled,
            "print_count": len(voice_prints),
            "total_matches": sum(vp.match_count for vp in voice_prints),
            "avg_snr": voice_prints[0].avg_snr if voice_prints else None,
        },
        "auth_mode": user.auth_mode.value if user.auth_mode else "password",
        "security_score": user.security_score,
    }


@router.post("/users/{user_id}/force-voice-reenroll")
async def force_voice_reenroll(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Force a user to re-enroll their voice print."""
    result = await db.execute(
        select(VoicePrint).where(and_(VoicePrint.user_id == user_id, VoicePrint.is_active.is_(True)))
    )
    prints = result.scalars().all()
    for vp in prints:
        vp.is_active = False
        vp.deleted_at = datetime.utcnow()

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if user:
        user.voice_enrolled = False
        user.security_score = user.compute_security_score()

    await db.flush()
    return {"message": f"Voice print reset for user {user_id}. Re-enrollment required."}


@router.get("/transactions", response_model=list[TransactionResponse])
async def admin_list_transactions(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin view of all network transactions."""
    result = await db.execute(select(Transaction).order_by(Transaction.created_at.desc()))
    txns = result.scalars().all()

    from backend.routers.transaction import get_transaction_response

    # Convert list using the helper function sequentially
    responses = []
    for t in txns:
        r = await get_transaction_response(db, t)
        responses.append(r)
    return responses


@router.patch("/transactions/{txn_id}/approve", response_model=TransactionResponse)
async def admin_approve_transaction(
    txn_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admin approves a transaction that has been dual-verified."""
    result = await db.execute(select(Transaction).where(Transaction.id == txn_id))
    txn = result.scalar_one_or_none()

    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if txn.status != TransactionStatus.RECEIVER_VERIFIED:
        raise HTTPException(status_code=400, detail="Transaction must be verified by both parties before approval")

    sender_res = await db.execute(select(User).where(User.id == txn.sender_id))
    sender = sender_res.scalar_one()

    receiver_res = await db.execute(select(User).where(User.id == txn.receiver_id))
    receiver = receiver_res.scalar_one()

    if sender.balance < txn.amount:
        txn.status = TransactionStatus.FAILED
        await db.commit()
        raise HTTPException(status_code=400, detail="Sender no longer has sufficient funds")

    # Execute transfer
    sender.balance -= txn.amount
    receiver.balance += txn.amount

    txn.status = TransactionStatus.COMPLETED
    txn.admin_approved = True

    await db.commit()

    from backend.routers.transaction import get_transaction_response

    return await get_transaction_response(db, txn)
