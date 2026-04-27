"""
Transaction Pydantic schemas.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from backend.models.transaction import TransactionStatus


class TransactionCreateRequest(BaseModel):
    receiver_email: str
    amount: float = Field(..., gt=0.0)


class TransactionResponse(BaseModel):
    id: str
    sender_email: str
    receiver_email: str
    amount: float
    status: TransactionStatus
    sender_face_verified: bool
    receiver_face_verified: bool
    admin_approved: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class TransactionFaceVerifyRequest(BaseModel):
    frames: list[str] = Field(..., min_length=1, max_length=10)
