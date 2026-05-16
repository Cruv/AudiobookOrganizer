import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash a password using PBKDF2-SHA256. Returns 'salt_hex:hash_hex'."""
    if salt is None:
        salt = os.urandom(32)
    pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"{salt.hex()}:{pw_hash.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored 'salt_hex:hash_hex' string."""
    try:
        salt_hex, _ = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        return hash_password(password, salt) == stored
    except (ValueError, AttributeError):
        return False


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="sessions")

    @staticmethod
    def create_token() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def default_expiry() -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=7)


class ApiToken(Base):
    """Long-lived bearer token for third-party automation.

    Lets users wire the app into a downloader (Sonarr/Radarr-style) or
    a webhook without sharing their session cookie. Stored as a hash
    of the token so a DB read alone doesn't yield the secret. The
    plaintext is only available at creation time.
    """

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # First 8 chars of the plaintext, kept so the UI can show the user
    # which token is which without revealing the full secret.
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    @staticmethod
    def create_plaintext() -> str:
        """Generate a new token. Caller stores the *hash*, not this value."""
        return "ao_" + secrets.token_urlsafe(40)

    @staticmethod
    def hash_token(plaintext: str) -> str:
        """SHA-256 hex digest of the plaintext."""
        return hashlib.sha256(plaintext.encode()).hexdigest()


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    used_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    @staticmethod
    def create_token() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def default_expiry() -> datetime:
        return datetime.now(timezone.utc) + timedelta(days=7)
