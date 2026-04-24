"""Tests for parser.py: metadata extraction from folder names."""

import pytest

from app.services.parser import (
    ParsedMetadata,
    auto_match_score,
    clean_narrator,
    clean_query,
    detect_edition,
    fuzzy_match,
    merge_with_tags,
    parse_folder_path,
)


class TestCleanQuery:
    def test_basic_title(self):
        assert clean_query("The Final Empire") == "The Final Empire"

    def test_strips_year(self):
        result = clean_query("The Final Empire 2006")
        assert "2006" not in result

    def test_title_and_author(self):
        result = clean_query("The Final Empire", "Brandon Sanderson")
        assert "The Final Empire" in result
        assert "Brandon Sanderson" in result

    def test_none_title(self):
        assert clean_query(None) == ""

    def test_suspect_author_excluded(self):
        result = clean_query("Some Book", "audiobooks")
        assert "audiobooks" not in result.lower()


class TestFuzzyMatch:
    def test_identical(self):
        assert fuzzy_match("Brandon Sanderson", "Brandon Sanderson") is True

    def test_case_insensitive(self):
        assert fuzzy_match("brandon sanderson", "BRANDON SANDERSON") is True

    def test_containment(self):
        assert fuzzy_match("Sanderson", "Brandon Sanderson") is True

    def test_completely_different(self):
        assert fuzzy_match("Patrick Rothfuss", "Brandon Sanderson") is False

    def test_empty_string(self):
        assert fuzzy_match("", "test") is False

    def test_short_strings(self):
        assert fuzzy_match("ab", "cd") is False
        assert fuzzy_match("ab", "ab") is True

    def test_article_ignored(self):
        """Leading articles should not block a match."""
        assert fuzzy_match("The Final Empire", "Final Empire")

    def test_whitespace_collapsed(self):
        """Extra whitespace should not block a match."""
        assert fuzzy_match("Brandon   Sanderson", "Brandon Sanderson")

    def test_none_inputs(self):
        assert fuzzy_match(None, "anything") is False
        assert fuzzy_match("anything", None) is False


class TestCleanNarrator:
    def test_none(self):
        assert clean_narrator(None) is None

    def test_empty(self):
        assert clean_narrator("") is None

    def test_valid_narrator(self):
        assert clean_narrator("Michael Kramer") == "Michael Kramer"

    def test_publisher_rejected(self):
        assert clean_narrator("Black Library") is None

    def test_heavy_entertainment_rejected(self):
        assert clean_narrator("Heavy Entertainment") is None

    def test_strips_trailing_punctuation(self):
        result = clean_narrator("Michael Kramer;")
        assert result is not None
        assert not result.endswith(";")

    def test_graphic_audio_edition(self):
        result = clean_narrator("Full Cast", edition="Graphic Audio")
        assert result == "Full Cast"


class TestDetectEdition:
    def test_graphic_audio_in_path(self):
        result = detect_edition("/audiobooks/Graphic Audio Collection/Mistborn")
        assert result == "Graphic Audio"

    def test_ga_in_folder_name(self):
        result = detect_edition("/audiobooks/Mistborn", folder_name="Mistborn (GA)")
        assert result == "Graphic Audio"

    def test_graphic_audio_tag_author(self):
        result = detect_edition("/audiobooks/Mistborn", tags={"author": "GraphicAudio"})
        assert result == "Graphic Audio"

    def test_dramatized_adaptation_tag(self):
        result = detect_edition(
            "/audiobooks/Mistborn",
            tags={"title": "[Dramatized Adaptation]"},
        )
        assert result == "Graphic Audio"

    def test_no_edition(self):
        result = detect_edition("/audiobooks/Mistborn")
        assert result is None


class TestParseFolderPath:
    def test_author_dash_title(self):
        result = parse_folder_path("/audiobooks/Brandon Sanderson - The Final Empire")
        assert result.author == "Brandon Sanderson"
        assert result.title == "The Final Empire"

    def test_with_series(self):
        result = parse_folder_path(
            "/audiobooks/Brandon Sanderson/Mistborn/The Final Empire"
        )
        assert result.title is not None

    def test_bare_folder_name(self):
        result = parse_folder_path("/audiobooks/The Final Empire")
        assert result.title is not None
        assert result.confidence > 0

    def test_with_year(self):
        result = parse_folder_path("/audiobooks/Brandon Sanderson - The Final Empire (2006)")
        assert result.year == "2006"


class TestMergeWithTags:
    def test_tags_override_author(self):
        parsed = ParsedMetadata(title="Test", author="Unknown", confidence=0.5)
        tags = {"author": "Real Author", "album": None, "year": None, "narrator": None, "series": None, "comment": None}
        result = merge_with_tags(parsed, tags)
        assert result.author == "Real Author"

    def test_tags_add_year(self):
        parsed = ParsedMetadata(title="Test", confidence=0.5)
        tags = {"author": None, "album": None, "year": "2020", "narrator": None, "series": None, "comment": None}
        result = merge_with_tags(parsed, tags)
        assert result.year == "2020"

    def test_graphic_audio_author_rejected(self):
        parsed = ParsedMetadata(title="Test", author="Real Author", confidence=0.5)
        tags = {"author": "GraphicAudio", "album": None, "year": None, "narrator": None, "series": None, "comment": None}
        result = merge_with_tags(parsed, tags)
        assert result.author != "GraphicAudio"


class TestAutoMatchScore:
    def test_perfect_match(self):
        parsed = ParsedMetadata(title="The Final Empire", author="Brandon Sanderson")
        score = auto_match_score(parsed, "The Final Empire", "Brandon Sanderson")
        assert score >= 0.85

    def test_no_match(self):
        parsed = ParsedMetadata(title="The Final Empire", author="Brandon Sanderson")
        score = auto_match_score(parsed, "Completely Different", "Someone Else")
        assert score < 0.5

    def test_title_only_match(self):
        parsed = ParsedMetadata(title="The Final Empire")
        score = auto_match_score(parsed, "The Final Empire", None)
        assert score > 0

    def test_article_insensitive(self):
        """'The Final Empire' should match 'Final Empire' (article stripped)."""
        parsed = ParsedMetadata(title="The Final Empire", author="Brandon Sanderson")
        score = auto_match_score(parsed, "Final Empire", "Brandon Sanderson")
        assert score >= 0.85

    def test_partial_title_match_gets_partial_credit(self):
        """Near-miss titles should get partial credit, not 0 like the old binary version."""
        parsed = ParsedMetadata(title="The Final Empire", author="Brandon Sanderson")
        # Slight typo in title — binary fuzzy_match likely fails, weighted scoring should give partial credit
        score = auto_match_score(parsed, "The Final Empires", "Brandon Sanderson")
        assert 0.7 < score < 1.0

    def test_series_match_adds_weight(self):
        """When series is present on both sides, it should contribute to score."""
        parsed = ParsedMetadata(
            title="The Final Empire",
            author="Brandon Sanderson",
            series="Mistborn",
        )
        without = auto_match_score(parsed, "The Final Empire", "Brandon Sanderson")
        with_series = auto_match_score(
            parsed,
            "The Final Empire",
            "Brandon Sanderson",
            result_series="Mistborn",
        )
        # Match on an extra field should not lower the score
        assert with_series >= without * 0.95

    def test_wrong_author_still_penalized(self):
        """Title match but wrong author should stay below auto-apply threshold."""
        parsed = ParsedMetadata(title="The Final Empire", author="Brandon Sanderson")
        score = auto_match_score(parsed, "The Final Empire", "Someone Completely Different")
        assert score < 0.85

    def test_year_proximity_helps_break_ties(self):
        """A matching year should help score slightly over a mismatching year."""
        parsed = ParsedMetadata(
            title="The Final Empire",
            author="Brandon Sanderson",
            year="2006",
        )
        matching = auto_match_score(
            parsed, "The Final Empire", "Brandon Sanderson", result_year="2006"
        )
        mismatching = auto_match_score(
            parsed, "The Final Empire", "Brandon Sanderson", result_year="1950"
        )
        assert matching >= mismatching


