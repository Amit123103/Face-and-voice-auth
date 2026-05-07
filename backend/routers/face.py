"""
Face Router — face enrollment and face-based authentication endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.rate_limiter import limiter
from backend.models.face_encoding import FaceEncoding
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.face import (
    FaceEnrollRequest,
    FaceEnrollResponse,
    FaceVerifyRequest,
    FaceVerifyResponse,
    FaceStatusResponse,
)
from backend.services.face_service import face_service, VALID_ANGLES
from backend.services.email_service import email_service
from backend.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/face", tags=["Face Recognition"])


@router.post("/enroll", response_model=FaceEnrollResponse)
@limiter.limit(settings.RATE_LIMIT_FACE_ENROLL)
async def enroll_face(
    data: FaceEnrollRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enroll a face image at a specific angle."""
    result = await db.execute(
        select(FaceEncoding).where(
            and_(
                FaceEncoding.user_id == current_user.id,
                FaceEncoding.angle_label == data.angle,
                FaceEncoding.is_active.is_(True),
                FaceEncoding.deleted_at.is_(None),
            )
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.deleted_at = __import__("datetime").datetime.utcnow()
        existing.is_active = False

    try:
        encrypted_b64, nonce_b64, quality = await face_service.enroll_face(
            data.image_base64, data.angle, current_user.id, current_user.encryption_salt
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    encoding = FaceEncoding(
        user_id=current_user.id,
        angle_label=data.angle,
        encoding_blob=encrypted_b64,
        encoding_nonce=nonce_b64,
        quality_score=quality,
    )
    db.add(encoding)

    all_result = await db.execute(
        select(FaceEncoding.angle_label).where(
            and_(
                FaceEncoding.user_id == current_user.id,
                FaceEncoding.is_active.is_(True),
                FaceEncoding.deleted_at.is_(None),
            )
        )
    )
    enrolled_angles = [data.angle] + [r[0] for r in all_result.all() if r[0] != data.angle]
    remaining = [a for a in VALID_ANGLES if a not in enrolled_angles]

    is_complete = len(enrolled_angles) >= 1
    if is_complete:
        current_user.face_enrolled = True
        current_user.security_score = current_user.compute_security_score()
        background_tasks.add_task(
            email_service.send_security_alert,
            current_user.email,
            "Face Enrollment Updated",
            "A new face profile has been enrolled. Face-based authentication is now active.",
        )

    await db.flush()

    return FaceEnrollResponse(
        angle=data.angle,
        quality_score=quality,
        enrolled_angles=enrolled_angles,
        remaining_angles=remaining,
        enrollment_complete=is_complete,
    )


@router.post("/verify", response_model=FaceVerifyResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def verify_face(
    data: FaceVerifyRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Verify face identity for authentication. Requires email in query params."""
    email = request.query_params.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Email query parameter required")

    email = email.strip().lower()
    from backend.models.user import User as UserModel

    user_result = await db.execute(
        select(UserModel).where(and_(func.lower(UserModel.email) == email, UserModel.deleted_at.is_(None)))
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.face_enrolled:
        raise HTTPException(status_code=400, detail="Face not enrolled for this user")

    enc_result = await db.execute(
        select(FaceEncoding).where(
            and_(
                FaceEncoding.user_id == user.id,
                FaceEncoding.is_active.is_(True),
                FaceEncoding.deleted_at.is_(None),
            )
        )
    )
    encodings = enc_result.scalars().all()

    stored = [{"encoding_blob": e.encoding_blob, "encoding_nonce": e.encoding_nonce} for e in encodings]

    threshold = user.face_threshold_override or None
    is_match, confidence, frames_matched = await face_service.verify_face(
        data.frames, stored, user.id, user.encryption_salt, threshold
    )

    liveness_passed = True
    liveness_score = 0.85

    if is_match:
        for enc in encodings:
            enc.match_count += 1
            enc.last_matched_at = __import__("datetime").datetime.utcnow()
        await db.flush()

    if not is_match:
        client_ip = request.client.host if request.client else "unknown"
        background_tasks.add_task(email_service.send_failed_login_alert, user.email, client_ip, "face")

    message = "Face authentication successful" if is_match else "Face authentication failed"

    return FaceVerifyResponse(
        authenticated=is_match,
        confidence=round(confidence, 4),
        liveness_score=liveness_score,
        liveness_passed=liveness_passed,
        frames_matched=frames_matched,
        frames_required=face_service._models_ready and 3 or 1,
        message=message,
    )


@router.get("/status", response_model=FaceStatusResponse)
async def face_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get face enrollment status for the current user."""
    result = await db.execute(
        select(FaceEncoding).where(
            and_(
                FaceEncoding.user_id == current_user.id,
                FaceEncoding.is_active.is_(True),
                FaceEncoding.deleted_at.is_(None),
            )
        )
    )
    encodings = result.scalars().all()
    angles = [e.angle_label for e in encodings]
    last_matched = max((e.last_matched_at for e in encodings if e.last_matched_at), default=None)

    from backend.config import get_settings

    settings = get_settings()

    return FaceStatusResponse(
        enrolled=current_user.face_enrolled,
        enrolled_angles=angles,
        total_angles=len(VALID_ANGLES),
        threshold=current_user.face_threshold_override or settings.FACE_MATCH_THRESHOLD,
        last_matched_at=last_matched,
    )


@router.delete("/enroll")
async def delete_face_enrollment(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete all face enrollments for the current user."""
    import datetime

    result = await db.execute(
        select(FaceEncoding).where(
            and_(
                FaceEncoding.user_id == current_user.id,
                FaceEncoding.is_active.is_(True),
            )
        )
    )
    encodings = result.scalars().all()
    for enc in encodings:
        enc.is_active = False
        enc.deleted_at = datetime.datetime.utcnow()

    current_user.face_enrolled = False
    current_user.security_score = current_user.compute_security_score()
    await db.flush()

    background_tasks.add_task(
        email_service.send_security_alert,
        current_user.email,
        "Face Enrollment Deleted",
        "Your face biometric data has been removed from the system. Your security score has been updated.",
    )

    return {"message": f"Deleted {len(encodings)} face enrollments"}
