"""
Voice authentication Pydantic schemas.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class VoiceEnrollStartResponse(BaseModel):
    challenge_pin: str
    session_id: str
    instructions: str
    min_samples: int
    max_samples: int


class VoiceSampleUploadRequest(BaseModel):
    session_id: str
    audio_base64: str


class VoiceVerifyRequest(BaseModel):
    email: str
    audio_base64: str
    challenge_pin: str = ""


class VoiceSampleUploadResponse(BaseModel):
    sample_number: int
    quality_score: float
    snr_db: float
    duration_seconds: float
    is_acceptable: bool
    feedback: List[str]
    total_samples: int
    min_samples_remaining: int


class VoiceEnrollCompleteResponse(BaseModel):
    enrolled: bool
    sample_count: int
    avg_quality: float
    avg_snr: float
    message: str


class VoiceVerifyResponse(BaseModel):
    authenticated: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    liveness_score: float = Field(..., ge=0.0, le=1.0)
    liveness_passed: bool
    challenge_matched: bool
    consecutive_matches: int
    matches_required: int
    message: str


class VoiceStatusResponse(BaseModel):
    enrolled: bool
    sample_count: int
    avg_snr: Optional[float] = None
    threshold: float
    last_used_at: Optional[datetime] = None
    is_active: bool


class VoicePassphraseEnrollRequest(BaseModel):
    audio_base64: str


class BiometricLoginRequest(BaseModel):
    face_frames: Optional[List[str]] = None
    voice_audio_base64: Optional[str] = None
    voice_challenge_response: Optional[str] = None
    voice_passphrase: Optional[str] = None


class BiometricLoginResponse(BaseModel):
    authenticated: bool
    face_confidence: Optional[float] = None
    voice_confidence: Optional[float] = None
    fusion_score: Optional[float] = None
    face_passed: Optional[bool] = None
    voice_passed: Optional[bool] = None
    passphrase_matched: Optional[bool] = None
    auth_method: str
    access_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: Optional[int] = None
    message: str
