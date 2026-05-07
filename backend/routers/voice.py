"""
Voice Router — voice enrollment and voice-based authentication endpoints.
"""

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.middleware.rate_limiter import limiter
from backend.models.voice_print import VoicePrint
from backend.models.user import User
from backend.routers.auth import get_current_user
from backend.schemas.voice import (
    VoiceEnrollStartResponse,
    VoiceSampleUploadRequest,
    VoiceSampleUploadResponse,
    VoiceEnrollCompleteResponse,
    VoiceVerifyRequest,
    VoiceVerifyResponse,
    VoiceStatusResponse,
    VoicePassphraseEnrollRequest,
)
from backend.services.voice_service import voice_service
from backend.services.voice_liveness_service import voice_liveness_service
from backend.services.email_service import email_service
from backend.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/api/voice", tags=["Voice Authentication"])

_enrollment_sessions: dict = {}


@router.post("/passphrase/set")
@limiter.limit("5/minute")
async def set_voice_passphrase(
    data: VoicePassphraseEnrollRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enroll a custom voice passphrase. Transcribes audio and saves it."""
    # actual_transcription = await voice_service.transcribe_audio(data.audio_base64)
    # Re-using transcription logic:
    actual_transcription = await voice_service.transcribe_audio(data.audio_base64)

    if not actual_transcription or len(actual_transcription) < 4:
        raise HTTPException(status_code=400, detail="Voice passphrase too short or not recognized. Speak clearly.")

    current_user.voice_passphrase = actual_transcription
    current_user.voice_passphrase_enabled = True
    current_user.security_score = current_user.compute_security_score()
    await db.commit()
    
    background_tasks.add_task(
        email_service.send_security_alert,
        current_user.email,
        "Voice Passphrase Enabled",
        f"A new custom voice password has been set: '{actual_transcription}'. This will now be required for secure transactions."
    )
    
    return {
        "status": "success",
        "passphrase": actual_transcription,
        "message": f"Voice password set to: '{actual_transcription}'"
    }


@router.post("/passphrase/disable")
async def disable_voice_passphrase(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable voice passphrase requirement."""
    current_user.voice_passphrase_enabled = False
    current_user.security_score = current_user.compute_security_score()
    await db.commit()
    
    background_tasks.add_task(
        email_service.send_security_alert,
        current_user.email,
        "Voice Passphrase Disabled",
        "Your voice passphrase requirement has been disabled. Your security score has been updated."
    )
    return {"status": "success", "message": "Voice password disabled"}


@router.post("/enroll/start", response_model=VoiceEnrollStartResponse)
@limiter.limit(settings.RATE_LIMIT_VOICE_ENROLL)
async def start_voice_enrollment(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Initiate voice enrollment, return a challenge PIN to speak aloud."""
    challenge_pin = "".join([str(secrets.randbelow(10)) for _ in range(4)])
    session_id = secrets.token_hex(16)

    _enrollment_sessions[session_id] = {
        "user_id": current_user.id,
        "challenge_pin": challenge_pin,
        "samples": [],
        "quality_scores": [],
        "snr_values": [],
    }

    return VoiceEnrollStartResponse(
        challenge_pin=challenge_pin,
        session_id=session_id,
        instructions=(
            f"Please speak the PIN '{challenge_pin}' clearly into your microphone. "
            f"You need at least {settings.VOICE_MIN_SAMPLES} voice samples, "
            f"up to {settings.VOICE_MAX_SAMPLES} for better accuracy."
        ),
        min_samples=settings.VOICE_MIN_SAMPLES,
        max_samples=settings.VOICE_MAX_SAMPLES,
    )


@router.post("/enroll/sample", response_model=VoiceSampleUploadResponse)
@limiter.limit(settings.RATE_LIMIT_VOICE_ENROLL)
async def upload_voice_sample(
    data: VoiceSampleUploadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a single voice sample for enrollment. Returns quality feedback."""
    session_data = _enrollment_sessions.get(data.session_id)
    if not session_data or session_data["user_id"] != current_user.id:
        raise HTTPException(status_code=400, detail="Invalid enrollment session")

    if len(session_data["samples"]) >= settings.VOICE_MAX_SAMPLES:
        raise HTTPException(status_code=400, detail="Maximum samples reached")

    is_ok, quality, snr, duration, feedback = voice_service.assess_sample_quality(
        data.audio_base64
    )

    if is_ok:
        try:
            enc_b64, nonce_b64, q, s, d = await voice_service.enroll_sample(
                data.audio_base64, current_user.id, current_user.encryption_salt
            )
            session_data["samples"].append({
                "ciphertext_b64": enc_b64,
                "nonce_b64": nonce_b64,
            })
            session_data["quality_scores"].append(quality)
            session_data["snr_values"].append(snr)
        except ValueError as e:
            feedback.append(str(e))
            is_ok = False

    total = len(session_data["samples"])
    remaining = max(0, settings.VOICE_MIN_SAMPLES - total)

    return VoiceSampleUploadResponse(
        sample_number=total,
        quality_score=quality,
        snr_db=snr,
        duration_seconds=duration,
        is_acceptable=is_ok,
        feedback=feedback,
        total_samples=total,
        min_samples_remaining=remaining,
    )


@router.post("/enroll/complete", response_model=VoiceEnrollCompleteResponse)
async def complete_voice_enrollment(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Finalize voice enrollment by averaging sample embeddings."""
    session_data = _enrollment_sessions.get(session_id)
    if not session_data or session_data["user_id"] != current_user.id:
        raise HTTPException(status_code=400, detail="Invalid enrollment session")

    if len(session_data["samples"]) < settings.VOICE_MIN_SAMPLES:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least {settings.VOICE_MIN_SAMPLES} samples, "
                   f"got {len(session_data['samples'])}",
        )

    old_result = await db.execute(
        select(VoicePrint).where(
            and_(
                VoicePrint.user_id == current_user.id,
                VoicePrint.is_active.is_(True),
            )
        )
    )
    old_prints = old_result.scalars().all()
    for vp in old_prints:
        vp.is_active = False
        vp.deleted_at = datetime.utcnow()

    avg_enc_b64, avg_nonce_b64 = await voice_service.compute_averaged_voiceprint(
        session_data["samples"], current_user.id, current_user.encryption_salt
    )

    avg_quality = sum(session_data["quality_scores"]) / len(session_data["quality_scores"])
    avg_snr = sum(session_data["snr_values"]) / len(session_data["snr_values"])

    voice_print = VoicePrint(
        user_id=current_user.id,
        embedding_blob=avg_enc_b64,
        embedding_nonce=avg_nonce_b64,
        sample_count=len(session_data["samples"]),
        avg_snr=round(avg_snr, 2),
        quality_score=round(avg_quality, 3),
    )
    db.add(voice_print)

    current_user.voice_enrolled = True
    current_user.security_score = current_user.compute_security_score()
    await db.flush()

    background_tasks.add_task(
        email_service.send_security_alert,
        current_user.email,
        "Voice Enrollment Complete",
        "Your voice profile has been successfully generated. Voice-based authentication is now active."
    )

    del _enrollment_sessions[session_id]

    return VoiceEnrollCompleteResponse(
        enrolled=True,
        sample_count=voice_print.sample_count,
        avg_quality=round(avg_quality, 3),
        avg_snr=round(avg_snr, 2),
        message="Voice enrollment completed successfully",
    )


@router.post("/verify", response_model=VoiceVerifyResponse)
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def verify_voice(
    data: VoiceVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Verify voice identity for authentication."""
    from backend.models.user import User as UserModel

    user_result = await db.execute(
        select(UserModel).where(
            and_(func.lower(UserModel.email) == data.email.strip().lower(), UserModel.deleted_at.is_(None))
        )
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.voice_enrolled:
        raise HTTPException(status_code=400, detail="Voice not enrolled")

    vp_result = await db.execute(
        select(VoicePrint).where(
            and_(
                VoicePrint.user_id == user.id,
                VoicePrint.is_active.is_(True),
                VoicePrint.deleted_at.is_(None),
            )
        )
    )
    voice_print = vp_result.scalar_one_or_none()
    if not voice_print:
        raise HTTPException(status_code=400, detail="No active voice print found")

    stored = {
        "embedding_blob": voice_print.embedding_blob,
        "embedding_nonce": voice_print.embedding_nonce,
    }
    threshold = user.voice_threshold_override or None

    is_match, cosine_sim = await voice_service.verify_voice(
        data.audio_base64, stored, user.id, user.encryption_salt, threshold
    )

    liveness_passed = True
    liveness_score = 0.85
    challenge_matched = True

    if data.challenge_pin:
        liveness_passed_result, liveness_score_result, liveness_details = (
            await voice_liveness_service.evaluate_liveness(data.audio_base64, data.challenge_pin)
        )
        liveness_passed = liveness_passed_result
        liveness_score = liveness_score_result
        challenge_matched = liveness_details.get("challenge_matched", True)

    authenticated = is_match and liveness_passed

    if authenticated:
        voice_print.match_count += 1
        voice_print.last_used_at = datetime.utcnow()
        await db.flush()

    return VoiceVerifyResponse(
        authenticated=authenticated,
        confidence=cosine_sim,
        liveness_score=liveness_score,
        liveness_passed=liveness_passed,
        challenge_matched=challenge_matched,
        consecutive_matches=1 if authenticated else 0,
        matches_required=settings.VOICE_CONSECUTIVE_MATCHES,
        message="Voice authentication successful" if authenticated else "Voice authentication failed",
    )


@router.get("/status", response_model=VoiceStatusResponse)
async def voice_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get voice enrollment status for the current user."""
    vp_result = await db.execute(
        select(VoicePrint).where(
            and_(
                VoicePrint.user_id == current_user.id,
                VoicePrint.is_active.is_(True),
                VoicePrint.deleted_at.is_(None),
            )
        )
    )
    vp = vp_result.scalar_one_or_none()

    return VoiceStatusResponse(
        enrolled=current_user.voice_enrolled,
        sample_count=vp.sample_count if vp else 0,
        avg_snr=vp.avg_snr if vp else None,
        threshold=current_user.voice_threshold_override or settings.VOICE_MATCH_THRESHOLD,
        last_used_at=vp.last_used_at if vp else None,
        is_active=vp.is_active if vp else False,
    )


@router.delete("/enroll")
async def delete_voice_enrollment(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete voice enrollment for the current user."""
    result = await db.execute(
        select(VoicePrint).where(
            and_(
                VoicePrint.user_id == current_user.id,
                VoicePrint.is_active.is_(True),
            )
        )
    )
    prints = result.scalars().all()
    for vp in prints:
        vp.is_active = False
        vp.deleted_at = datetime.utcnow()

    current_user.voice_enrolled = False
    current_user.security_score = current_user.compute_security_score()
    await db.flush()

    background_tasks.add_task(
        email_service.send_security_alert,
        current_user.email,
        "Voice Enrollment Deleted",
        "Your voice biometric data has been removed from the system."
    )

    return {"message": f"Deleted {len(prints)} voice prints"}
