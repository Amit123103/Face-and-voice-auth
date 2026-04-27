"""
Face recognition Pydantic schemas.
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class FaceEnrollRequest(BaseModel):
    angle: str = Field(..., pattern=r"^(front|left_30|right_30|up_15|down_15)$")
    image_base64: str = Field(..., min_length=100)


class FaceEnrollResponse(BaseModel):
    angle: str
    quality_score: float
    enrolled_angles: List[str]
    remaining_angles: List[str]
    enrollment_complete: bool


class FaceVerifyRequest(BaseModel):
    frames: List[str] = Field(..., min_length=1, max_length=10)


class FaceVerifyResponse(BaseModel):
    authenticated: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    liveness_score: float = Field(..., ge=0.0, le=1.0)
    liveness_passed: bool
    frames_matched: int
    frames_required: int
    message: str


class FaceStatusResponse(BaseModel):
    enrolled: bool
    enrolled_angles: List[str]
    total_angles: int
    threshold: float
    last_matched_at: Optional[datetime] = None
