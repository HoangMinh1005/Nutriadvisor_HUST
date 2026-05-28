"""Unit tests for the feature store module."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.ml.feature_store import FEATURE_COLUMNS, NUTRIENT_COLUMNS, FeatureStore


def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "food_id": 1,
                "canonical_key": "beef",
                "canonical_name_en": "Beef",
                "energy_kcal": 100.0,
                "protein_g": 10.0,
                "fat_g": 5.0,
                "carbs_g": 2.0,
                "vitamin_a_mcg": 0.0,
                "beta_carotene_mcg": 1.0,
                "vitamin_c_mg": 2.0,
                "calcium_mg": 3.0,
                "iron_mg": 4.0,
                "zinc_mg": 5.0,
                "sodium_mg": 6.0,
                "cholesterol_mg": 7.0,
                "magnesium_mg": 8.0,
                "transfat_mg": 9.0,
            },
            {
                "food_id": 2,
                "canonical_key": "chicken",
                "canonical_name_en": "Chicken",
                "energy_kcal": 200.0,
                "protein_g": 20.0,
                "fat_g": 10.0,
                "carbs_g": 4.0,
                "vitamin_a_mcg": 1.0,
                "beta_carotene_mcg": 2.0,
                "vitamin_c_mg": 3.0,
                "calcium_mg": 4.0,
                "iron_mg": 5.0,
                "zinc_mg": 6.0,
                "sodium_mg": 7.0,
                "cholesterol_mg": 8.0,
                "magnesium_mg": 9.0,
                "transfat_mg": 10.0,
            },
        ]
    )


def test_normalize_creates_norm_columns_and_vectors(tmp_path: Path) -> None:
    store = FeatureStore(db_url="postgresql://example", cache_dir=tmp_path)
    normalized = store.normalize_nutrients(_sample_frame())

    for column in NUTRIENT_COLUMNS:
        assert f"{column}_norm" in normalized.columns

    assert "vector" in normalized.columns
    assert "feature_vector" in normalized.columns

    first_vector = normalized.iloc[0]["vector"]
    assert isinstance(first_vector, np.ndarray)
    assert first_vector.shape == (14,)

    matrix, metadata = store.to_feature_matrix(normalized)
    assert matrix.shape == (2, 14)
    assert metadata[0]["canonical_key"] == "beef"


def test_normalize_handles_constant_columns(tmp_path: Path) -> None:
    store = FeatureStore(db_url="postgresql://example", cache_dir=tmp_path)
    frame = _sample_frame()
    for column in NUTRIENT_COLUMNS:
        frame[column] = 5.0

    normalized = store.normalize_nutrients(frame)
    for column in NUTRIENT_COLUMNS:
        assert normalized[f"{column}_norm"].tolist() == [0.0, 0.0]


def test_cache_and_load_snapshot_round_trip(tmp_path: Path) -> None:
    store = FeatureStore(db_url="postgresql://example", cache_dir=tmp_path)
    payload = {"feature_columns": list(FEATURE_COLUMNS), "count": 2}

    cache_path = store.cache_features("snapshot", payload)
    assert cache_path.exists()

    loaded = store.load_cached_features("snapshot")
    assert loaded == payload