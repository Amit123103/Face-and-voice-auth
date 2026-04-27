"""
VoicePrint ORM model — stores encrypted 256-d speaker embeddings per user.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    Float,
    Text,
    Integer,
    ForeignKey,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class VoicePrint(Base):
    __tablename__ = "voice_prints"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    embedding_blob = Column(Text, nullable=False)
    embedding_nonce = Column(String(44), nullable=True)
    sample_count = Column(Integer, default=0, nullable=False)
    avg_snr = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    threshold_override = Column(Float, nullable=True)
    enrolled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    match_count = Column(Integer, default=0, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="voice_prints")
