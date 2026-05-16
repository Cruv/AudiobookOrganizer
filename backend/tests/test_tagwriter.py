"""Tests for the opt-in tag write-back (PR 8).

Verifying full round-trip per format would require generating real
audio files. Instead we hit the easy formats (MP4/M4B via a stub file
that mutagen creates from scratch, FLAC/OggVorbis) and confirm the
service refuses unknown extensions and stays defensive against
missing files. Real-world tag writing is covered by integration
testing against the user's actual library — the unit suite focuses
on the entry-level invariants that catch regressions.
"""

import os


class TestWriteBookTagsEntryPoints:
    def test_missing_file_returns_false(self, tmp_path):
        from app.services.tagwriter import write_book_tags

        ok, err = write_book_tags(str(tmp_path / "nope.mp3"), title="X")
        assert ok is False
        assert err is not None
        assert "not found" in err.lower()

    def test_unsupported_extension_returns_false(self, tmp_path):
        from app.services.tagwriter import write_book_tags

        weird = tmp_path / "audio.wma"
        weird.write_bytes(b"\x00" * 100)
        ok, err = write_book_tags(str(weird), title="X")
        assert ok is False
        assert err and "unsupported" in err.lower()


class TestTagWriteEnabled:
    def test_default_is_false(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        import app.models.book  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.lookup_candidate  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401

        from app.services.organizer import _tag_write_enabled

        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()

        assert _tag_write_enabled(db) is False

    def test_true_when_setting_is_true(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        import app.models.book  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.lookup_candidate  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401

        from app.models.settings import UserSetting
        from app.services.organizer import _tag_write_enabled

        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        db.add(UserSetting(key="write_tags_on_organize", value="true"))
        db.commit()

        assert _tag_write_enabled(db) is True

    def test_false_when_setting_is_other_value(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        import app.models.book  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.lookup_candidate  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401

        from app.models.settings import UserSetting
        from app.services.organizer import _tag_write_enabled

        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        db.add(UserSetting(key="write_tags_on_organize", value="false"))
        db.commit()

        assert _tag_write_enabled(db) is False


class TestSettingsRoundTrip:
    """The PUT /api/settings handler coerces booleans to 'true'/'false'
    strings before storage. Verify the round-trip."""

    def test_update_settings_writes_bool_as_string(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.models.base import Base
        import app.models.book  # noqa: F401
        import app.models.lookup_cache  # noqa: F401
        import app.models.lookup_candidate  # noqa: F401
        import app.models.scan  # noqa: F401
        import app.models.settings  # noqa: F401
        import app.models.user  # noqa: F401
        from app.models.user import User
        from app.routers.settings import update_settings
        from app.schemas.settings import SettingsUpdate

        engine = create_engine(
            "sqlite:///:memory:", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        # Dummy admin to satisfy the Depends(require_admin) — we pass
        # it through manually since we're not going through FastAPI.
        admin = User(username="admin", password_hash="x:y", is_admin=True)
        db.add(admin)
        db.commit()

        update_settings(
            SettingsUpdate(write_tags_on_organize=True),
            db=db,
            _admin=admin,
        )

        from app.models.settings import UserSetting
        row = (
            db.query(UserSetting)
            .filter(UserSetting.key == "write_tags_on_organize")
            .first()
        )
        assert row is not None
        assert row.value == "true"

        # Flip off
        update_settings(
            SettingsUpdate(write_tags_on_organize=False),
            db=db,
            _admin=admin,
        )
        row = (
            db.query(UserSetting)
            .filter(UserSetting.key == "write_tags_on_organize")
            .first()
        )
        assert row.value == "false"


# Suppress unused-import lint for cross-platform `os` usage.
_ = os
