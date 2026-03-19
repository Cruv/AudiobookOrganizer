"""Tests for organizer.py: path building and sanitization."""

import pytest

from app.services.organizer import build_output_path, sanitize_path_component


class TestSanitizePathComponent:
    def test_removes_illegal_chars(self):
        assert sanitize_path_component('Book: The "Test"') == "Book_ The _Test_"

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
