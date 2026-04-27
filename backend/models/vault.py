"""
SecretVault ORM model — Secure text storage using per-user AES-256-GCM encryption.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from backend.database import Base


class SecretVault(Base):
    __tablename__ = "secret_vault"
    __table_args__ = (
        Index('idx_vault_owner_cat_type', 'user_id', 'category', 'secret_type'),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False, default="Personal")
    secret_type = Column(String(50), nullable=False, default="Note")
    
    ciphertext_b64 = Column(Text, nullable=False)
    nonce_b64 = Column(String(100), nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    user = relationship("User")
