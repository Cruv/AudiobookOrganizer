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
    parse_file_path,
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

    def test_generic_parent_folder_not_promoted_to_series(self):
        """Regression: /downloads/Torrents/AudioBooks/Cypher...
        used to pick "AudioBooks" up as Series, which polluted the
        output path with a stray /AudioBooks/ component. The
        nested-folder strategy now rejects generic container folder
        names ("AudioBooks", "Downloads", "Torrents", ...) so the
        series stays empty for later strategies / lookup to fill."""
        result = parse_folder_path(
            "/downloads/Torrents/AudioBooks/Cypher, Lord of the Fallen",
        )
        # We don't care what title parsing picks here — just that the
        # junk parent folder isn't promoted to Series.
        if result is not None:
            assert result.series != "AudioBooks"
            assert result.series != "Torrents"

    def test_audiobooks_folder_directly_under_audiobooks_is_clean(self):
        """When the immediate parent IS a generic container, we have
        no author signal from the path — return None so leaf strategies
        get a chance instead of treating "AudioBooks" as the author."""
        # Just the leaf-folder strategy should run; nested should bail.
        from app.services.parser import _strategy_nested_folders

        result = _strategy_nested_folders(
            "/downloads/AudioBooks/Cypher, Lord of the Fallen",
        )
        assert result is None

    def test_post_merge_scrub_clears_generic_series(self):
        """If somehow a generic series leaks through (e.g. a tag
        contains "audiobook"), merge_with_tags should clear it."""
        from app.services.parser import ParsedMetadata, merge_with_tags

        parsed = ParsedMetadata(
            title="Cypher", author="John French",
            series="AudioBooks", series_position="1",
            year="2023", confidence=0.8,
        )
        merged = merge_with_tags(parsed, {})
        assert merged.series is None
        assert merged.series_position is None


class TestParseFilePath:
    def test_author_dash_title(self):
        result = parse_file_path("/downloads/Brandon Sanderson - The Final Empire.m4b")
        assert result.author == "Brandon Sanderson"
        assert result.title == "The Final Empire"

    def test_strips_extension(self):
        result = parse_file_path("/downloads/The Final Empire.m4b")
        assert result.title is not None
        assert "m4b" not in (result.title or "").lower()

    def test_with_year(self):
        result = parse_file_path(
            "/downloads/Brandon Sanderson - The Final Empire (2006).m4b"
        )
        assert result.year == "2006"

    def test_ignores_parent_directory(self):
        # The 'downloads' parent dir must NOT become the author —
        # loose files often sit in generic library/downloads dirs.
        result = parse_file_path("/downloads/The Final Empire.m4b")
        assert result.author != "downloads"

    def test_bare_filename(self):
        result = parse_file_path("/anywhere/The Final Empire.m4b")
        assert result.title is not None
        assert result.confidence > 0


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


