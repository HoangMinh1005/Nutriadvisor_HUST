"""Unit tests for data.scripts.load_structured_to_db helper functions."""

import pytest
from data.scripts.load_structured_to_db import (
    _clean_text,
    _to_float,
    _to_bool,
    _dedupe_rows_by_canonical_key,
)


class TestCleanText:
    """Test _clean_text() helper function."""

    def test_clean_text_none_returns_empty(self):
        """None input should return empty string."""
        assert _clean_text(None) == ""

    def test_clean_text_strips_whitespace(self):
        """Leading/trailing whitespace should be removed."""
        assert _clean_text("  hello  ") == "hello"
        assert _clean_text("\t world \n") == "world"

    def test_clean_text_converts_nan_variants(self):
        """Common null-like strings should return empty string."""
        assert _clean_text("nan") == ""
        assert _clean_text("NaN") == ""
        assert _clean_text("NULL") == ""
        assert _clean_text("null") == ""
        assert _clean_text("None") == ""
        assert _clean_text("none") == ""

    def test_clean_text_preserves_valid_text(self):
        """Valid text should be preserved."""
        assert _clean_text("Beef") == "Beef"
        assert _clean_text("thit bo") == "thit bo"
        assert _clean_text("250 kcal") == "250 kcal"

    def test_clean_text_handles_numbers(self):
        """Numbers should be converted to string."""
        assert _clean_text(123) == "123"
        assert _clean_text(45.67) == "45.67"


class TestToFloat:
    """Test _to_float() helper function."""

    def test_to_float_valid_integers(self):
        """Valid integers should be converted to float."""
        assert _to_float("100") == 100.0
        assert _to_float("0") == 0.0
        assert _to_float(50) == 50.0

    def test_to_float_valid_floats(self):
        """Valid floats should be converted correctly."""
        assert _to_float("25.5") == 25.5
        assert _to_float("0.95") == 0.95
        assert _to_float(3.14) == 3.14

    def test_to_float_null_values_return_zero(self):
        """None and null-like strings should return 0.0."""
        assert _to_float(None) == 0.0
        assert _to_float("nan") == 0.0
        assert _to_float("NULL") == 0.0
        assert _to_float("") == 0.0

    def test_to_float_invalid_strings_return_zero(self):
        """Invalid numeric strings should return 0.0."""
        assert _to_float("abc") == 0.0
        assert _to_float("12x34") == 0.0
        assert _to_float("not a number") == 0.0

    def test_to_float_whitespace(self):
        """Whitespace-only strings should return 0.0."""
        assert _to_float("   ") == 0.0
        assert _to_float("\t") == 0.0

    def test_to_float_negative_numbers(self):
        """Negative numbers should be handled correctly."""
        assert _to_float("-50.5") == -50.5
        assert _to_float("-1") == -1.0


class TestToBool:
    """Test _to_bool() helper function."""

    def test_to_bool_truthy_strings(self):
        """Common truthy values should return True."""
        assert _to_bool("true") is True
        assert _to_bool("True") is True
        assert _to_bool("TRUE") is True
        assert _to_bool("1") is True
        assert _to_bool("yes") is True
        assert _to_bool("Yes") is True
        assert _to_bool("y") is True

    def test_to_bool_falsy_strings(self):
        """Everything else should return False."""
        assert _to_bool("false") is False
        assert _to_bool("False") is False
        assert _to_bool("0") is False
        assert _to_bool("no") is False
        assert _to_bool("") is False
        assert _to_bool(None) is False
        assert _to_bool("random") is False

    def test_to_bool_with_whitespace(self):
        """Whitespace should be trimmed before checking."""
        assert _to_bool("  true  ") is True
        assert _to_bool("\t1\n") is True
        assert _to_bool("  false  ") is False


class TestDedupeRowsByCanonicalKey:
    """Test _dedupe_rows_by_canonical_key() deduplication logic."""

    def test_dedupe_keeps_first_occurrence(self, sample_csv_rows):
        """First occurrence of duplicate key should be kept."""
        result = _dedupe_rows_by_canonical_key(sample_csv_rows)
        
        # Find beef in result
        beef_rows = [r for r in result if r.get("canonical_key") == "beef"]
        assert len(beef_rows) == 1
        # First beef should have 'Beef' not 'Beef (variant)'
        assert beef_rows[0]["canonical_name_en"] == "Beef"
        assert beef_rows[0]["source_id"] == "NIN_001"

    def test_dedupe_removes_empty_keys(self, sample_csv_rows):
        """Rows with empty canonical_key should be filtered out."""
        result = _dedupe_rows_by_canonical_key(sample_csv_rows)
        
        # Result should only have beef and chicken (3 unique valid keys)
        assert len(result) == 2
        canonical_keys = [r.get("canonical_key") for r in result]
        assert "" not in canonical_keys

    def test_dedupe_preserves_order(self):
        """Order of first occurrences should be preserved."""
        rows = [
            {"canonical_key": "beef", "order": "1"},
            {"canonical_key": "chicken", "order": "2"},
            {"canonical_key": "beef", "order": "1dup"},  # dup
            {"canonical_key": "pork", "order": "3"},
        ]
        result = _dedupe_rows_by_canonical_key(rows)
        
        assert len(result) == 3
        assert result[0]["canonical_key"] == "beef"
        assert result[1]["canonical_key"] == "chicken"
        assert result[2]["canonical_key"] == "pork"

    def test_dedupe_empty_input(self):
        """Empty input should return empty list."""
        result = _dedupe_rows_by_canonical_key([])
        assert result == []

    def test_dedupe_single_row(self):
        """Single row should be returned as-is."""
        rows = [{"canonical_key": "beef", "name": "Beef"}]
        result = _dedupe_rows_by_canonical_key(rows)
        assert result == rows

    def test_dedupe_all_unique_keys(self):
        """All unique keys should be preserved."""
        rows = [
            {"canonical_key": "beef"},
            {"canonical_key": "chicken"},
            {"canonical_key": "pork"},
            {"canonical_key": "fish"},
        ]
        result = _dedupe_rows_by_canonical_key(rows)
        assert len(result) == 4

    def test_dedupe_counts_match(self, sample_csv_rows):
        """Deduped count should be correct."""
        result = _dedupe_rows_by_canonical_key(sample_csv_rows)
        # 4 input rows: beef (2 dups), chicken (1), empty (1)
        # Expected output: 2 (beef + chicken)
        assert len(result) == 2


class TestHelperFunctionsIntegration:
    """Integration tests combining multiple helper functions."""

    def test_food_row_cleaning_pipeline(self):
        """Test realistic food row data cleaning."""
        row = {
            "canonical_key": "  beef  ",
            "canonical_name_en": "  Beef  ",
            "name_vi": "  Thịt bò  ",
            "energy_kcal": "  250.5  ",
            "protein_g": "NaN",
            "confidence_score": "  0.95  ",
            "is_estimated": "  false  ",
        }
        
        # Simulate the pipeline
        canonical_key = _clean_text(row["canonical_key"])
        name_en = _clean_text(row["canonical_name_en"])
        energy = _to_float(row["energy_kcal"])
        protein = _to_float(row["protein_g"])  # NaN
        confidence = _to_float(row["confidence_score"])
        is_estimated = _to_bool(row["is_estimated"])
        
        assert canonical_key == "beef"
        assert name_en == "Beef"
        assert energy == 250.5
        assert protein == 0.0
        assert confidence == 0.95
        assert is_estimated is False

    def test_csv_row_with_all_null_values(self):
        """Rows with all null values should still be processable."""
        row = {
            "canonical_key": "test",
            "energy_kcal": "nan",
            "protein_g": None,
            "confidence_score": "",
        }
        
        energy = _to_float(row["energy_kcal"])
        protein = _to_float(row["protein_g"])
        confidence = _to_float(row["confidence_score"])
        
        assert energy == 0.0
        assert protein == 0.0
        assert confidence == 0.0
