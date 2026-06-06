"""Unit tests for data.scripts.load_price_estimates_to_db helper functions."""

import pytest

from data.scripts.load_price_estimates_to_db import _clean_text, _to_float, _to_int, _iter_price_items


class TestCleanText:
    def test_clean_text_none_returns_empty(self):
        assert _clean_text(None) == ""

    def test_clean_text_trims_and_normalizes_nulls(self):
        assert _clean_text("  hello  ") == "hello"
        assert _clean_text("NaN") == ""
        assert _clean_text("NULL") == ""


class TestToInt:
    def test_to_int_parses_numeric_values(self):
        assert _to_int("100") == 100
        assert _to_int("100.8") == 100
        assert _to_int(2500) == 2500

    def test_to_int_returns_zero_for_invalid_values(self):
        assert _to_int(None) == 0
        assert _to_int("") == 0
        assert _to_int("abc") == 0


class TestToFloat:
    def test_to_float_parses_numeric_values(self):
        assert _to_float("100") == 100.0
        assert _to_float("100.5") == 100.5
        assert _to_float(2) == 2.0

    def test_to_float_returns_zero_for_invalid_values(self):
        assert _to_float(None) == 0.0
        assert _to_float("") == 0.0
        assert _to_float("abc") == 0.0


class TestIterPriceItems:
    def test_iter_price_items_returns_only_dict_items(self):
        defaults = {
            "items": [
                {"canonical_key": "beef", "price_100g": 15000},
                "ignore-me",
                123,
                {"canonical_key": "rice", "price_100g": 3000},
            ]
        }

        items = _iter_price_items(defaults)

        assert len(items) == 2
        assert items[0]["canonical_key"] == "beef"
        assert items[1]["canonical_key"] == "rice"

    def test_iter_price_items_rejects_non_list(self):
        with pytest.raises(ValueError):
            _iter_price_items({"items": {"canonical_key": "beef"}})
