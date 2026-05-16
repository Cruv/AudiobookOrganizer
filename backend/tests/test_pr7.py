"""Tests for PR 7: API tokens (hash storage + auth flow) + integrity check."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_db():
    from app.models.base import Base
    import app.models.book  # noqa: F401
    import app.models.lookup_cache  # noqa: F401
    import app.models.lookup_candidate  # noqa: F401
    import app.models.scan  # noqa: F401
    import app.models.settings  # noqa: F401
    import app.models.user  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class TestApiTokenModel:
    def test_plaintext_has_known_prefix(self):
        from app.models.user import ApiToken

        plaintext = ApiToken.create_plaintext()
        assert plaintext.startswith("ao_")
        assert len(plaintext) > 30

    def test_hash_is_stable_and_64_hex_chars(self):
        from app.models.user import ApiToken

        plaintext = "ao_test_value"
        h1 = ApiToken.hash_token(plaintext)
        h2 = ApiToken.hash_token(plaintext)
        assert h1 == h2
        assert len(h1) == 64
        assert all(c in "0123456789abcdef" for c in h1)

    def test_different_plaintext_different_hash(self):
        from app.models.user import ApiToken

        assert ApiToken.hash_token("a") != ApiToken.hash_token("b")


class TestApiTokenEndpoints:
    def _make_user(self, db):
        from app.models.user import User, UserSession, hash_password

        user = User(username="testuser", password_hash=hash_password("password123"))
        db.add(user)
        db.flush()
        session = UserSession(
            user_id=user.id,
            token=UserSession.create_token(),
            expires_at=UserSession.default_expiry(),
        )
        db.add(session)
        db.commit()
        return user, session

    def test_create_token_returns_plaintext_once(self):
        from app.routers.auth import (
            CreateApiTokenRequest, create_api_token,
        )

        db = _make_db()
        _, session = self._make_user(db)

        resp = create_api_token(
            CreateApiTokenRequest(name="sonarr"),
            db=db,
            session_token=session.token,
        )
        assert resp.name == "sonarr"
        assert resp.token.startswith("ao_")
        assert resp.token_prefix.startswith("ao_")

        # The stored row should have only the hash, not the plaintext.
        from app.models.user import ApiToken
        row = db.query(ApiToken).filter(ApiToken.id == resp.id).first()
        assert row is not None
        assert row.token_hash == ApiToken.hash_token(resp.token)
        # Stored token_prefix must match what the response advertised.
        assert row.token_prefix == resp.token_prefix

    def test_list_tokens_shows_prefix_only(self):
        from app.routers.auth import (
            CreateApiTokenRequest, create_api_token, list_api_tokens,
        )

        db = _make_db()
        _, session = self._make_user(db)
        created = create_api_token(
            CreateApiTokenRequest(name="x"), db=db, session_token=session.token,
        )

        tokens = list_api_tokens(db=db, session_token=session.token)
        assert len(tokens) == 1
        assert tokens[0].name == "x"
        assert tokens[0].token_prefix == created.token_prefix
        # Plaintext shouldn't appear in the list response.
        assert not hasattr(tokens[0], "token")

    def test_revoke_token_marks_revoked(self):
        from app.routers.auth import (
            CreateApiTokenRequest, create_api_token, revoke_api_token,
        )

        db = _make_db()
        _, session = self._make_user(db)
        created = create_api_token(
            CreateApiTokenRequest(name="x"), db=db, session_token=session.token,
        )
        revoke_api_token(created.id, db=db, session_token=session.token)

        from app.models.user import ApiToken
        row = db.query(ApiToken).filter(ApiToken.id == created.id).first()
        assert row.revoked is True

    def test_create_requires_name(self):
        from fastapi import HTTPException

        from app.routers.auth import (
            CreateApiTokenRequest, create_api_token,
        )

        db = _make_db()
        _, session = self._make_user(db)

        try:
            create_api_token(
                CreateApiTokenRequest(name=""),
                db=db, session_token=session.token,
            )
            assert False, "should have raised"
        except HTTPException as e:
            assert e.status_code == 400


class TestIntegrityCheck:
    def test_missing_file_is_unreadable(self, tmp_path):
        from app.services.integrity import check_file

        status, detail = check_file(str(tmp_path / "nope.mp3"))
        assert status == "unreadable"
        assert detail is not None

    def test_zero_byte_file_is_unreadable(self, tmp_path):
        from app.services.integrity import check_file

        bad = tmp_path / "empty.mp3"
        bad.write_bytes(b"")
        status, _ = check_file(str(bad))
        # mutagen returns None for empty / unrecognized → 'unreadable'.
        assert status == "unreadable"

    def test_random_bytes_is_unreadable(self, tmp_path):
        from app.services.integrity import check_file

        bad = tmp_path / "garbage.mp3"
        bad.write_bytes(b"\x00\x01\x02" * 200)
        status, _ = check_file(str(bad))
        # mutagen may return None for garbage that doesn't match any
        # format, or it may return a parseable header with no info.
        assert status in {"unreadable", "unchecked"}
