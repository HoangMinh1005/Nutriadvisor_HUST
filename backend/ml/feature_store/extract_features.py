"""Feature store extraction, normalization, and caching utilities."""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg

NUTRIENT_COLUMNS: tuple[str, ...] = (
    "energy_kcal",
    "protein_g",
    "fat_g",
    "carbs_g",
    "vitamin_a_mcg",
    "beta_carotene_mcg",
    "vitamin_c_mg",
    "calcium_mg",
    "iron_mg",
    "zinc_mg",
    "sodium_mg",
    "cholesterol_mg",
    "magnesium_mg",
    "transfat_mg",
)

FEATURE_COLUMNS: tuple[str, ...] = (
    "food_id",
    "canonical_key",
    "canonical_name_en",
    *NUTRIENT_COLUMNS,
)


class FeatureStore:
    """Load food nutrient vectors from PostgreSQL and cache ML-ready snapshots."""

    def __init__(self, db_url: str | None = None, cache_dir: str | Path | None = None) -> None:
        self.db_url = db_url or os.getenv("DATABASE_URL", "")
        if not self.db_url:
            raise RuntimeError("DATABASE_URL is not configured")

        self.cache_dir = Path(cache_dir or Path("data") / "ml" / "features")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def extract_food_vectors(self) -> pd.DataFrame:
        """Extract the canonical 14D food feature table from PostgreSQL."""
        query = """
            SELECT
                f.food_id,
                f.canonical_key,
                f.canonical_name_en,
                n.energy_kcal,
                n.protein_g,
                n.fat_g,
                n.carbs_g,
                n.vitamin_a_mcg,
                n.beta_carotene_mcg,
                n.vitamin_c_mg,
                n.calcium_mg,
                n.iron_mg,
                n.zinc_mg,
                n.sodium_mg,
                n.cholesterol_mg,
                n.magnesium_mg,
                n.transfat_mg
            FROM foods f
            JOIN food_nutrients n ON n.food_id = f.food_id
            ORDER BY f.food_id;
        """

        conn = psycopg.connect(self.db_url)
        try:
            with conn.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
                columns = [desc.name for desc in cursor.description]
        finally:
            conn.close()

        frame = pd.DataFrame(rows, columns=columns)
        return frame.loc[:, list(FEATURE_COLUMNS)].copy()

    def normalize_nutrients(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Normalize nutrient columns to [0, 1] and append vector outputs."""
        normalized = frame.copy(deep=True)
        for column in NUTRIENT_COLUMNS:
            if column not in normalized.columns:
                raise KeyError(f"Missing nutrient column: {column}")

            values = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0).astype(float)
            minimum = float(values.min())
            maximum = float(values.max())

            if maximum > minimum:
                normalized[f"{column}_norm"] = (values - minimum) / (maximum - minimum)
            else:
                normalized[f"{column}_norm"] = 0.0

        normalized["vector"] = normalized[[f"{column}_norm" for column in NUTRIENT_COLUMNS]].apply(
            lambda row: np.asarray(row.tolist(), dtype=np.float32),
            axis=1,
        )
        normalized["feature_vector"] = normalized["vector"]
        return normalized

    def to_feature_matrix(self, normalized_frame: pd.DataFrame) -> tuple[np.ndarray, list[dict[str, Any]]]:
        """Convert a normalized frame to matrix + metadata for ML consumers."""
        nutrient_norm_columns = [f"{column}_norm" for column in NUTRIENT_COLUMNS]
        matrix = normalized_frame[nutrient_norm_columns].to_numpy(dtype=np.float32, copy=True)
        metadata = normalized_frame[["food_id", "canonical_key", "canonical_name_en"]].to_dict(orient="records")
        return matrix, metadata

    def cache_features(self, name: str, data: Any) -> Path:
        """Persist a feature artifact to the cache directory."""
        cache_file = self.cache_dir / f"{name}.pkl"
        with cache_file.open("wb") as handle:
            pickle.dump(data, handle)
        return cache_file

    def load_cached_features(self, name: str) -> Any:
        """Load a previously cached feature artifact."""
        cache_file = self.cache_dir / f"{name}.pkl"
        with cache_file.open("rb") as handle:
            return pickle.load(handle)

    def build_snapshot(self, snapshot_name: str = "food_feature_snapshot") -> dict[str, Any]:
        """Extract, normalize, and cache a complete feature snapshot."""
        extracted = self.extract_food_vectors()
        normalized = self.normalize_nutrients(extracted)
        matrix, metadata = self.to_feature_matrix(normalized)

        snapshot = {
            "raw": extracted,
            "normalized": normalized,
            "matrix": matrix,
            "metadata": metadata,
            "feature_columns": list(FEATURE_COLUMNS),
            "nutrient_columns": list(NUTRIENT_COLUMNS),
        }
        self.cache_features(snapshot_name, snapshot)
        return snapshot