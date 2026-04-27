"""
FaceVoiceAuth — Application Configuration
Loads all environment variables with validation and sensible defaults.
"""

import os
import base64
import secrets
from pathlib import Path
from functools import lru_cache
from typing import List, Optional

from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    APP_NAME: str = "FaceVoiceAuth"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./facevoiceauth.db"
    ASYNC_DATABASE_URL: str = "sqlite+aiosqlite:///./facevoiceauth.db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # JWT / Auth
    SECRET_KEY: str = secrets.token_hex(32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Encryption
    MASTER_KEY: str = base64.b64encode(secrets.token_bytes(32)).decode()

    # Face Recognition
    FACE_MATCH_THRESHOLD: float = 0.45
    MIN_FACE_LIVENESS_SCORE: float = 0.75
    FACE_MULTI_FRAME_COUNT: int = 3
    FACE_MAX_ANGLES: int = 5
    FACE_MODEL_DIR: str = str(Path(__file__).parent / "models_data")

    # Voice Authentication
    VOICE_MATCH_THRESHOLD: float = 0.82
    MIN_VOICE_LIVENESS_SCORE: float = 0.80
    VOICE_MIN_SAMPLES: int = 3
    VOICE_MAX_SAMPLES: int = 10
    VOICE_MIN_DURATION: float = 3.0
    VOICE_MAX_DURATION: float = 10.0
    VOICE_MIN_SNR: float = 15.0
    VOICE_CONSECUTIVE_MATCHES: int = 2

    # Biometric Fusion
    FACE_FUSION_WEIGHT: float = 0.6
    VOICE_FUSION_WEIGHT: float = 0.4
    FUSION_MIN_SCORE: float = 0.80
    FUSION_INDIVIDUAL_MIN: float = 0.60

    # Lockout
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_SECONDS: int = 60
    LOCKOUT_MULTIPLIERS: List[int] = [1, 5, 30, 1440]

    # CORS
    CORS_ORIGINS: str = "http://localhost,http://localhost:3000,http://localhost:8080"

    # Admin Seed
    ADMIN_EMAIL: str = "admin@facevoiceauth.local"
    ADMIN_PASSWORD: str = "ChangeMe!2024Secure"

    # SMTP
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Backup
    BACKUP_DIR: str = "/data/backups"
    BACKUP_RETENTION_DAYS: int = 30

    # Sentry
    SENTRY_DSN: Optional[str] = None

    # Rate Limiting
    RATE_LIMIT_LOGIN: str = "10/minute"
    RATE_LIMIT_FACE_ENROLL: str = "3/minute"
    RATE_LIMIT_VOICE_ENROLL: str = "3/minute"
    RATE_LIMIT_GENERAL: str = "100/minute"

    # Performance — lower bcrypt rounds in dev for faster auth
    BCRYPT_ROUNDS: int = 10

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors(cls, v: str) -> str:
        return v

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def master_key_bytes(self) -> bytes:
        return base64.b64decode(self.MASTER_KEY)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "allow"}


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
