"""
Biometric Router — combined face+voice authentication endpoint.
"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.rate_limiter import limiter
from backend.models.user import User, AuthMode
from backend.models.face_encoding import FaceEncoding
from backend.models.voice_print import VoicePrint
from backend.schemas.voice import BiometricLoginRequest, BiometricLoginResponse
from backend.services.face_service import face_service
from backend.services.voice_service import voice_service
from backend.services.biometric_fusion_service import biometric_fusion_service
from backend.services.auth_service import auth_service
from backend.services.email_service import email_service
from backend.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/biometric", tags=["Biometric Fusion"])


@router.post("/login", response_model=BiometricLoginResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def biometric_login(
    data: BiometricLoginRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    email: str = "",
    db: AsyncSession = Depends(get_db),
):
    """
    Combined face+voice biometric login.
    Runs both verification pipelines in parallel, applies fusion scoring.
    """
    if not email:
        email = request.query_params.get("email", "")
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    user_result = await db.execute(
        select(User).where(and_(User.email == email, User.deleted_at.is_(None)))
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_locked and user.lockout_until and datetime.utcnow() < user.lockout_until:
        raise HTTPException(status_code=423, detail="Account is locked")

    face_available = data.face_frames is not None and len(data.face_frames) > 0
    voice_available = data.voice_audio_base64 is not None and len(data.voice_audio_base64) > 0

    face_confidence = None
    voice_confidence = None
    face_passed = None
    voice_passed = None

    async def run_face_verification():
        nonlocal face_confidence, face_passed
        if not face_available or not user.face_enrolled:
            return

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
        if not encodings:
            return

        stored = [
            {"encoding_blob": e.encoding_blob, "encoding_nonce": e.encoding_nonce}
            for e in encodings
        ]

        is_match, conf, frames = await face_service.verify_face(
            data.face_frames, stored, user.id, user.encryption_salt
        )
        face_confidence = conf
        face_passed = is_match

    async def run_voice_verification():
        nonlocal voice_confidence, voice_passed
        if not voice_available or not user.voice_enrolled:
            return

        vp_result = await db.execute(
            select(VoicePrint).where(
                and_(
                    VoicePrint.user_id == user.id,
                    VoicePrint.is_active.is_(True),
                    VoicePrint.deleted_at.is_(None),
                )
            )
        )
        vp = vp_result.scalar_one_or_none()
        if not vp:
            return

        stored = {
            "embedding_blob": vp.embedding_blob,
            "embedding_nonce": vp.embedding_nonce,
        }

        is_match, sim = await voice_service.verify_voice(
            data.voice_audio_base64, stored, user.id, user.encryption_salt
        )
        voice_confidence = sim
        voice_passed = is_match

    # Run both verifications concurrently for speed
    await asyncio.gather(
        run_face_verification(),
        run_voice_verification(),
    )

    if user.auth_mode == AuthMode.FACE_VOICE:
        authenticated, fusion_score, reason, audit = biometric_fusion_service.evaluate_fusion(
            face_confidence=face_confidence,
            voice_confidence=voice_confidence,
            fallback_allowed=user.fallback_allowed,
            face_available=face_available and user.face_enrolled,
            voice_available=voice_available and user.voice_enrolled,
        )
        auth_method = "face_voice"
    elif user.auth_mode == AuthMode.FACE:
        authenticated = face_passed is True
        fusion_score = face_confidence
        auth_method = "face"
    elif user.auth_mode == AuthMode.VOICE:
        authenticated = voice_passed is True
        fusion_score = voice_confidence
        auth_method = "voice"
    else:
        raise HTTPException(
            status_code=400,
            detail="User auth mode is password-only. Use /api/auth/login instead.",
        )

    passphrase_matched = None
    if authenticated and user.voice_passphrase_enabled:
        if not data.voice_audio_base64:
             authenticated = False
             message = "Voice passphrase audio required for this account."
        else:
            match, trans = await voice_service.verify_passphrase(data.voice_audio_base64, user.voice_passphrase)
            passphrase_matched = match
            if not match:
                authenticated = False
                message = f"Voice password mismatch. You said: '{trans}'"

    access_token = None
    expires_in = None

    if authenticated:
        access_token, expires_in = auth_service.create_access_token(
            user.id, user.role.value, auth_method
        )
        refresh_token, _ = auth_service.create_refresh_token()

        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        await auth_service.create_session(
            db, user, refresh_token, client_ip, user_agent, auth_method
        )

        background_tasks.add_task(email_service.send_login_alert, user.email, client_ip, auth_method)

        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            max_age=7 * 24 * 3600,
            path="/api/auth/refresh",
        )

        user.failed_login_attempts = 0
        user.is_locked = False
        user.lockout_until = None
    else:
        client_ip = request.client.host if request.client else "unknown"
        background_tasks.add_task(email_service.send_failed_login_alert, user.email, client_ip, auth_method)
        
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.is_locked = True
            user.lockout_until = datetime.utcnow()

    await db.flush()

    return BiometricLoginResponse(
        authenticated=authenticated,
        face_confidence=face_confidence,
        voice_confidence=voice_confidence,
        fusion_score=fusion_score,
        face_passed=face_passed,
        voice_passed=voice_passed,
        passphrase_matched=passphrase_matched,
        auth_method=auth_method,
        access_token=access_token,
        expires_in=expires_in,
        message="Authentication successful" if authenticated else "Authentication failed",
    )
