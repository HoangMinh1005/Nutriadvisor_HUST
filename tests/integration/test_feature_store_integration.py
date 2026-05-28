"""Integration tests for the feature store against the live database."""

from __future__ import annotations

from pathlib import Path

from backend.ml.feature_store import FEATURE_COLUMNS, NUTRIENT_COLUMNS, FeatureStore


def test_feature_store_extracts_and_normalizes_database_vectors(database_url: str, tmp_path: Path) -> None:
    store = FeatureStore(db_url=database_url, cache_dir=tmp_path)

    extracted = store.extract_food_vectors()
    assert list(extracted.columns) == list(FEATURE_COLUMNS)
    assert len(extracted) == 9609
    assert extracted["food_id"].min() == 1
    assert extracted["food_id"].max() == 9609

    normalized = store.normalize_nutrients(extracted)
    for column in NUTRIENT_COLUMNS:
        assert f"{column}_norm" in normalized.columns

    matrix, metadata = store.to_feature_matrix(normalized)
    assert matrix.shape == (9609, 14)
    assert len(metadata) == 9609
    assert metadata[0]["food_id"] == 1


def test_feature_store_cache_round_trip(database_url: str, tmp_path: Path) -> None:
    store = FeatureStore(db_url=database_url, cache_dir=tmp_path)
    snapshot = store.build_snapshot(snapshot_name="feature_store_test_snapshot")

    cached = store.load_cached_features("feature_store_test_snapshot")
    assert cached["matrix"].shape == snapshot["matrix"].shape
    assert cached["metadata"][0]["food_id"] == snapshot["metadata"][0]["food_id"]