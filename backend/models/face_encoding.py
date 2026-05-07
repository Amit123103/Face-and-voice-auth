"""
FaceEncoding ORM model — stores encrypted 128-d face embeddings per user.
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
    ForeignKey,
    Integer,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class FaceEncoding(Base):
    __tablename__ = "face_encodings"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    angle_label = Column(String(20), nullable=False)
    encoding_blob = Column(Text, nullable=False)
    encoding_nonce = Column(String(44), nullable=True)
    quality_score = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    enrolled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_matched_at = Column(DateTime, nullable=True)
    match_count = Column(Integer, default=0, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="face_encodings")
