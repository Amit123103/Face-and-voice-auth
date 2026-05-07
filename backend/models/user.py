"""
User ORM model — core user entity with multi-modal auth support.
"""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Integer,
    Float,
    Enum,
    Text,
)
from sqlalchemy.orm import relationship

from backend.database import Base


class UserRole(str, PyEnum):
    USER = "user"
    ADMIN = "admin"


class AuthMode(str, PyEnum):
    PASSWORD = "password"
    FACE = "face"
    VOICE = "voice"
    FACE_VOICE = "face_voice"


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    auth_mode = Column(Enum(AuthMode), default=AuthMode.PASSWORD, nullable=False)
    fallback_allowed = Column(Boolean, default=False, nullable=False)

    balance = Column(Float, default=1000.0, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_locked = Column(Boolean, default=False, nullable=False)

    failed_login_attempts = Column(Integer, default=0, nullable=False)
    lockout_until = Column(DateTime, nullable=True)
    last_failed_login = Column(DateTime, nullable=True)
    lockout_count = Column(Integer, default=0, nullable=False)

    totp_secret = Column(String(32), nullable=True)
    totp_enabled = Column(Boolean, default=False, nullable=False)
    backup_codes = Column(Text, nullable=True)

    face_enrolled = Column(Boolean, default=False, nullable=False)
    face_threshold_override = Column(Float, nullable=True)
    voice_enrolled = Column(Boolean, default=False, nullable=False)
    voice_threshold_override = Column(Float, nullable=True)
    voice_passphrase = Column(String(255), nullable=True)
    voice_passphrase_enabled = Column(Boolean, default=False, nullable=False)

    security_score = Column(Float, default=0.0, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    last_login_ip = Column(String(45), nullable=True)
    last_login_method = Column(String(20), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    encryption_salt = Column(String(44), nullable=True)

    face_encodings = relationship("FaceEncoding", back_populates="user", cascade="all, delete-orphan")
    voice_prints = relationship("VoicePrint", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("SessionRecord", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_soft_deleted(self) -> bool:
        return self.deleted_at is not None

    def compute_security_score(self) -> float:
        score = 20.0
        if self.totp_enabled:
            score += 25.0
        if self.face_enrolled:
            score += 25.0
        if self.voice_enrolled:
            score += 20.0
        if self.auth_mode == AuthMode.FACE_VOICE:
            score += 10.0
        if self.voice_passphrase_enabled:
            score += 10.0
        return min(score, 100.0)
