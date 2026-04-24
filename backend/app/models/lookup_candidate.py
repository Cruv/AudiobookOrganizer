"""Persisted lookup candidates for a book.

A candidate represents one lookup result that was considered for a book
during auto-lookup. Storing them lets users:
  - See every candidate considered, not just the applied one.
  - Re-apply a different provider's result without hitting the API again.
  - Reject candidates so they don't get re-suggested on re-lookup.
  - Understand *why* a particular candidate scored the way it did
    (match_breakdown JSON contains per-field similarities).
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class LookupCandidate(Base):
    __tablename__ = "lookup_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_rank: Mapped[int] = mapped_column(Integer, default=0)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    series: Mapped[str | None] = mapped_column(Text, nullable=True)
    series_position: Mapped[str | None] = mapped_column(String(20), nullable=True)
    year: Mapped[str | None] = mapped_column(String(10), nullable=True)
    narrator: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provider's own confidence (how sure the provider is about its result).
    raw_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # How well this result matched the book's parsed metadata, 0–1.
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    # Provider trust weight applied when this candidate was scored.
    trust_weight: Mapped[float] = mapped_column(Float, default=1.0)
    # Final ranking score: match_score * trust_weight. The candidate
    # with the highest ranking_score is the "best" one.
    ranking_score: Mapped[float] = mapped_column(Float, default=0.0)

    # JSON-encoded per-field similarity breakdown. Shape:
    # {"title": 0.95, "author": 1.0, "series": null, "year": 1.0, ...}
    match_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Set to True when the user explicitly rejects this result. Rejected
    # candidates stay in the DB so re-lookup can avoid re-suggesting them.
    rejected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set to True on the currently-applied candidate. At most one per book.
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    book: Mapped["Book"] = relationship(back_populates="candidates")


# Avoid circular import at module load time
from app.models.book import Book  # noqa: E402, F401
