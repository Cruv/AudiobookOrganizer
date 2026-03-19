"""Tests for user auth: password hashing, session management."""

from app.models.user import hash_password, verify_password, UserSession, Invite
from datetime import datetime, timezone


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "test_password_123"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True

    def test_wrong_password(self):
        hashed = hash_password("correct_password")
        assert verify_password("wrong_password", hashed) is False

    def test_hash_format(self):
        hashed = hash_password("test")
        assert ":" in hashed
        salt_hex, hash_hex = hashed.split(":", 1)
        assert len(salt_hex) == 64  # 32 bytes = 64 hex chars

    def test_different_salts(self):
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2  # Different salts

    def test_verify_malformed_hash(self):
        assert verify_password("test", "not_a_hash") is False
        assert verify_password("test", "") is False


class TestUserSession:
    def test_create_token(self):
        token = UserSession.create_token()
        assert len(token) > 32
        assert isinstance(token, str)

    def test_default_expiry(self):
        expiry = UserSession.default_expiry()
        now = datetime.now(timezone.utc)
        # Should be ~7 days in the future
        diff = (expiry - now).total_seconds()
        assert 6 * 86400 < diff < 8 * 86400


class TestInvite:
    def test_create_token(self):
        token = Invite.create_token()
        assert len(token) > 16
        assert isinstance(token, str)

    def test_default_expiry(self):
        expiry = Invite.default_expiry()
        now = datetime.now(timezone.utc)
        diff = (expiry - now).total_seconds()
        assert 6 * 86400 < diff < 8 * 86400
