"""
Authentication Service — password auth, JWT tokens, TOTP 2FA, lockout, sessions.
"""

import hashlib
import io
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

import bcrypt
import pyotp
import qrcode
import qrcode.image.pil
import base64
from jose import jwt, JWTError
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.user import User, AuthMode
from backend.models.session import SessionRecord

settings = get_settings()


class AuthService:
    """Handles all authentication logic including password, JWT, TOTP, and sessions."""

    def hash_password(self, password: str) -> str:
        """Hash a password with bcrypt at configurable cost factor."""
        salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def verify_password(self, password: str, hashed: str) -> bool:
        """Check a password against its bcrypt hash."""
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

    def create_access_token(self, user_id: str, role: str, auth_method: str) -> Tuple[str, int]:
        """Create a JWT access token with claims."""
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        expire = datetime.utcnow() + expires_delta
        payload = {
            "sub": user_id,
            "role": role,
            "auth_method": auth_method,
            "type": "access",
            "exp": expire,
            "iat": datetime.utcnow(),
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        return token, int(expires_delta.total_seconds())

    def create_refresh_token(self) -> Tuple[str, datetime]:
        """Create a secure random refresh token."""
        token = secrets.token_urlsafe(64)
        expires = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        return token, expires

    def hash_refresh_token(self, token: str) -> str:
        """SHA-256 hash of the refresh token for storage."""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def decode_access_token(self, token: str) -> Optional[dict]:
        """Decode and validate a JWT access token."""
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            if payload.get("type") != "access":
                return None
            return payload
        except JWTError:
            return None

    def generate_totp_secret(self) -> str:
        """Generate a new TOTP secret."""
        return pyotp.random_base32()

    def get_totp_uri(self, secret: str, email: str) -> str:
        """Get the provisioning URI for QR code generation."""
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name=settings.APP_NAME)

    def generate_qr_base64(self, uri: str) -> str:
        """Generate a QR code image as base64 PNG."""
        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="white", back_color="#0a0a0f")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    def verify_totp(self, secret: str, code: str) -> bool:
        """Verify a TOTP code with a 30-second window tolerance."""
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)

    def generate_backup_codes(self, count: int = 8) -> List[str]:
        """Generate one-time backup codes for 2FA recovery."""
        return [secrets.token_hex(4).upper() for _ in range(count)]

    async def register_user(
        self, db: AsyncSession, email: str, username: str, full_name: str, password: str, auth_mode: str = "password"
    ) -> User:
        """Register a new user."""
        from backend.services.encryption_service import encryption_service

        email = email.strip().lower()
        existing = await db.execute(select(User).where((func.lower(User.email) == email) | (User.username == username)))
        if existing.scalar_one_or_none():
            raise ValueError("User with this email or username already exists")

        hashed_pw = self.hash_password(password)
        salt = encryption_service.generate_salt()

        user = User(
            email=email,
            username=username,
            full_name=full_name,
            hashed_password=hashed_pw,
            auth_mode=AuthMode(auth_mode),
            encryption_salt=salt,
            is_verified=True,
        )
        user.security_score = user.compute_security_score()
        db.add(user)
        await db.flush()
        return user

    async def authenticate_password(self, db: AsyncSession, email: str, password: str) -> Optional[User]:
        """Authenticate a user by email and password."""
        email = email.strip().lower()
        result = await db.execute(select(User).where(and_(func.lower(User.email) == email, User.deleted_at.is_(None))))
        user = result.scalar_one_or_none()
        if not user:
            return None

        if user.is_locked and user.lockout_until:
            if datetime.utcnow() < user.lockout_until:
                return None
            else:
                user.is_locked = False
                user.failed_login_attempts = 0

        if not self.verify_password(password, user.hashed_password):
            await self._handle_failed_login(db, user)
            return None

        user.failed_login_attempts = 0
        user.lockout_count = 0
        user.is_locked = False
        user.lockout_until = None
        return user

    async def _handle_failed_login(self, db: AsyncSession, user: User) -> None:
        """Handle failed login attempt with progressive lockout."""
        user.failed_login_attempts += 1
        user.last_failed_login = datetime.utcnow()

        if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.is_locked = True
            user.lockout_count += 1

            multipliers = settings.LOCKOUT_MULTIPLIERS
            idx = min(user.lockout_count - 1, len(multipliers) - 1)
            duration = settings.LOCKOUT_DURATION_SECONDS * multipliers[idx]

            if user.lockout_count >= len(multipliers):
                user.lockout_until = datetime.utcnow() + timedelta(days=365)
            else:
                user.lockout_until = datetime.utcnow() + timedelta(seconds=duration)

        await db.flush()

    async def create_session(
        self, db: AsyncSession, user: User, refresh_token: str, ip: str, user_agent: str, auth_method: str
    ) -> SessionRecord:
        """Create a new authenticated session."""
        _, expires = self.create_refresh_token()
        session = SessionRecord(
            user_id=user.id,
            refresh_token_hash=self.hash_refresh_token(refresh_token),
            ip_address=ip,
            user_agent=user_agent,
            auth_method=auth_method,
            expires_at=expires,
        )
        db.add(session)

        user.last_login_at = datetime.utcnow()
        user.last_login_ip = ip
        user.last_login_method = auth_method
        await db.flush()
        return session

    async def get_user_sessions(self, db: AsyncSession, user_id: str) -> List[SessionRecord]:
        """Get all active sessions for a user."""
        result = await db.execute(
            select(SessionRecord)
            .where(
                and_(
                    SessionRecord.user_id == user_id,
                    SessionRecord.is_active.is_(True),
                    SessionRecord.revoked_at.is_(None),
                )
            )
            .order_by(SessionRecord.created_at.desc())
        )
        return list(result.scalars().all())

    async def revoke_session(self, db: AsyncSession, session_id: str) -> bool:
        """Revoke a specific session."""
        result = await db.execute(select(SessionRecord).where(SessionRecord.id == session_id))
        session = result.scalar_one_or_none()
        if session:
            session.is_active = False
            session.revoked_at = datetime.utcnow()
            await db.flush()
            return True
        return False

    async def revoke_all_sessions(self, db: AsyncSession, user_id: str, except_session_id: Optional[str] = None) -> int:
        """Revoke all sessions for a user, optionally keeping current session."""
        stmt = (
            update(SessionRecord)
            .where(
                and_(
                    SessionRecord.user_id == user_id,
                    SessionRecord.is_active.is_(True),
                )
            )
            .values(is_active=False, revoked_at=datetime.utcnow())
        )
        if except_session_id:
            stmt = stmt.where(SessionRecord.id != except_session_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def refresh_access_token(self, db: AsyncSession, refresh_token: str) -> Optional[Tuple[str, int, str]]:
        """Validate refresh token and issue a new access token."""
        token_hash = self.hash_refresh_token(refresh_token)
        result = await db.execute(
            select(SessionRecord).where(
                and_(
                    SessionRecord.refresh_token_hash == token_hash,
                    SessionRecord.is_active.is_(True),
                    SessionRecord.revoked_at.is_(None),
                )
            )
        )
        session = result.scalar_one_or_none()
        if not session or session.is_expired:
            return None

        user_result = await db.execute(select(User).where(User.id == session.user_id))
        user = user_result.scalar_one_or_none()
        if not user or not user.is_active or user.is_soft_deleted:
            return None

        session.last_activity = datetime.utcnow()
        access_token, expires_in = self.create_access_token(user.id, user.role.value, session.auth_method)
        await db.flush()
        return access_token, expires_in, user.id

    async def get_user_by_id(self, db: AsyncSession, user_id: str) -> Optional[User]:
        """Fetch a user by ID, excluding soft-deleted records."""
        result = await db.execute(select(User).where(and_(User.id == user_id, User.deleted_at.is_(None))))
        return result.scalar_one_or_none()

    def check_password_strength(self, password: str) -> dict:
        """Evaluate password strength with feedback."""
        score = 0
        feedback = []

        if len(password) >= 8:
            score += 1
        else:
            feedback.append("Password should be at least 8 characters")
        if len(password) >= 12:
            score += 1
        if any(c.isupper() for c in password) and any(c.islower() for c in password):
            score += 1
        else:
            feedback.append("Mix uppercase and lowercase letters")
        if any(c.isdigit() for c in password):
            score += 0.5
        else:
            feedback.append("Add numbers")
        if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
            score += 0.5
        else:
            feedback.append("Add special characters")

        score = min(int(score), 4)
        crack_times = ["instant", "minutes", "hours", "days", "centuries"]
        return {
            "score": score,
            "feedback": feedback,
            "crack_time": crack_times[score],
            "is_strong": score >= 3,
        }


auth_service = AuthService()
