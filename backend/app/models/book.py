from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scanned_folder_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scanned_folders.id"), unique=True, nullable=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    series: Mapped[str | None] = mapped_column(Text, nullable=True)
    series_position: Mapped[str | None] = mapped_column(String(20), nullable=True)
    year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    narrator: Mapped[str | None] = mapped_column(Text, nullable=True)
    edition: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="parsed"
    )
    # Legacy conflated score. Kept for backwards compatibility with the
    # existing Review UI; new code should prefer the split fields below
    # and compute this as max(parse_confidence, match_confidence).
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # How sure we are about the locally parsed/merged metadata (folder
    # names + audio tags). Set once at parse time, not changed by lookup.
    parse_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # How well the currently-applied lookup result matched the parsed
    # data. 0.0 when no lookup has been applied (source == "parsed").
    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    # When locked, this book is frozen: neither re-scan nor auto-lookup
    # will ever mutate its metadata. Stronger than is_confirmed (which
    # only says "user approves current values"); locked says "don't even
    # consider changing these values automatically".
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    organize_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    purge_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="not_purged"
    )
    lookup_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    scanned_folder: Mapped["ScannedFolder | None"] = relationship(
        back_populates="book"
    )
    files: Mapped[list["BookFile"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    candidates: Mapped[list["LookupCandidate"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )


class BookFile(Base):
    __tablename__ = "book_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    file_format: Mapped[str | None] = mapped_column(String(10), nullable=True)
    destination_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    copy_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    tag_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    tag_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    tag_album: Mapped[str | None] = mapped_column(Text, nullable=True)
    tag_year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tag_track: Mapped[str | None] = mapped_column(String(10), nullable=True)
    tag_narrator: Mapped[str | None] = mapped_column(Text, nullable=True)

    book: Mapped["Book"] = relationship(back_populates="files")


# Imported for the relationship's type-annotation string resolution.
from app.models.lookup_candidate import LookupCandidate  # noqa: E402, F401
from app.models.scan import ScannedFolder  # noqa: E402, F401
