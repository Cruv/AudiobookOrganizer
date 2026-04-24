"""Tests for organizer.py: path building and sanitization."""

import pytest

from app.services.organizer import build_output_path, sanitize_path_component


class TestSanitizePathComponent:
    def test_replaces_filesystem_illegal_chars(self):
        # Backslashes, slashes, quotes etc. become underscores.
        assert sanitize_path_component('Book "Test" / Other') == "Book _Test_ _ Other"

    def test_colon_becomes_spaced_dash(self):
        # Colons are nominally legal on Linux but break Windows and confuse
        # media servers; we render them as " - " for readability.
        assert sanitize_path_component("Black Legion: Warhammer") == "Black Legion - Warhammer"

    def test_commas_are_stripped(self):
        # User preference — "40,000" reads as "40000" in paths.
        assert sanitize_path_component("Warhammer 40,000") == "Warhammer 40000"

    def test_combined_colon_and_comma(self):
        # The motivating example from v1.9.3 — an iTunes match with both.
        assert (
            sanitize_path_component("Black Legion: Warhammer 40,000")
            == "Black Legion - Warhammer 40000"
        )

    def test_dedupes_adjacent_dashes_from_substitutions(self):
        # "Foo - : Bar" would otherwise produce "Foo -  -  Bar".
        assert sanitize_path_component("Foo - : Bar") == "Foo - Bar"

    def test_strips_dots_and_spaces(self):
        assert sanitize_path_component("  test. ") == "test"

    def test_max_length(self):
        long_name = "A" * 300
        result = sanitize_path_component(long_name)
        assert len(result) <= 200

    def test_empty_after_strip(self):
        result = sanitize_path_component("...")
        assert result == ""


class TestBuildOutputPath:
    class FakeBook:
        def __init__(self, **kwargs):
            self.title = kwargs.get("title")
            self.author = kwargs.get("author")
            self.series = kwargs.get("series")
            self.series_position = kwargs.get("series_position")
            self.year = kwargs.get("year")
            self.narrator = kwargs.get("narrator")
            self.edition = kwargs.get("edition")

    def test_basic_pattern(self):
        book = self.FakeBook(
            title="The Final Empire",
            author="Brandon Sanderson",
            year="2006",
        )
        result = build_output_path(book, "{Author}/{Title} ({Year})", "/output")
        assert "Brandon Sanderson" in result
        assert "The Final Empire" in result
        assert "2006" in result

    def test_missing_tokens_collapsed(self):
        book = self.FakeBook(title="Test Book", author="Author")
        result = build_output_path(book, "{Author}/{Series}/{Title}", "/output")
        # Series segment should be collapsed since series is None
        assert "Series" not in result

    def test_edition_bracketed(self):
        book = self.FakeBook(
            title="Mistborn",
            author="Sanderson",
            edition="Graphic Audio",
        )
        result = build_output_path(
            book, "{Author}/{Title} {EditionBracketed}", "/output"
        )
        assert "[Graphic Audio]" in result

    def test_narrator_braced(self):
        book = self.FakeBook(
            title="Test", author="Author", narrator="Michael Kramer"
        )
        result = build_output_path(
            book, "{Author}/{Title} {NarratorBraced}", "/output"
        )
        assert "{Michael Kramer}" in result

    def test_fallback_on_empty_pattern(self):
        book = self.FakeBook(title="Fallback Book")
        result = build_output_path(book, "{Series}", "/output")
        assert "Fallback Book" in result

    def test_path_traversal_sanitized(self):
        book = self.FakeBook(title="../../etc/passwd", author="hack")
        result = build_output_path(book, "{Author}/{Title}", "/output")
        # Illegal chars (/ : etc.) are sanitized to _, preventing traversal
        assert result.startswith("/output")
        assert "etc/passwd" not in result

    def test_empty_parens_cleaned(self):
        book = self.FakeBook(title="Test", author="Author")
        result = build_output_path(
            book, "{Author}/{Title} ({Year}) {EditionBracketed}", "/output"
        )
        assert "()" not in result
        assert "[]" not in result

    def test_missing_author_uses_unknown_fallback(self):
        """Books without an author should bucket into Unknown Author, not flatten to root."""
        book = self.FakeBook(title="Orphan Book", author=None)
        result = build_output_path(book, "{Author}/{Title}", "/output")
        # Must NOT be flat at root level — must be nested under Unknown Author
        assert "Unknown Author" in result
        assert "Orphan Book" in result

    def test_missing_title_uses_unknown_title_fallback(self):
        """Books without a title should bucket into Unknown Title."""
        book = self.FakeBook(title=None, author="Some Author")
        result = build_output_path(book, "{Author}/{Title}", "/output")
        assert "Some Author" in result
        assert "Unknown Title" in result

    def test_optional_tokens_still_collapse(self):
        """Series, year etc. should still be collapsed when empty, not substituted."""
        book = self.FakeBook(title="T", author="A")
        result = build_output_path(book, "{Author}/{Series}/{Year}/{Title}", "/output")
        # Series and Year segments should collapse, not become "Unknown Series"
        assert "Unknown Series" not in result
        assert "Unknown Year" not in result
        assert result.endswith("T")
