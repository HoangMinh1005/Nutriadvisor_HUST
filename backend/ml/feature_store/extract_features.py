"""Feature store extraction, normalization, and caching utilities."""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / "backend" / ".env")
load_dotenv(ROOT_DIR / ".env")

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
        """Extract the canonical 14D food feature table from PostgreSQL with extra metadata."""
        query = """
            SELECT
                f.food_id,
                f.canonical_key,
                f.canonical_name_en,
                f.name_vi,
                g.group_code AS category,
                COALESCE(f.price_100g_vnd, 15000) AS price_100g,
                f.source_name,
                f.source_priority,
                f.tags,
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
            JOIN food_groups g ON f.food_group_id = g.food_group_id
            WHERE f.is_active = TRUE
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
        
        # Convert tags list to set
        frame["tags"] = frame["tags"].apply(lambda t: set(t) if t else set())
        
        all_cols = list(FEATURE_COLUMNS) + ["name_vi", "category", "price_100g", "source_name", "source_priority", "tags"]
        existing_cols = [c for c in all_cols if c in frame.columns]
        return frame.loc[:, existing_cols].copy()

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
        
        metadata = []
        for _, row in normalized_frame.iterrows():
            item = {
                "food_id": int(row["food_id"]),
                "canonical_key": row.get("canonical_key", ""),
                "canonical_name_en": row.get("canonical_name_en", ""),
                "name_vi": row.get("name_vi", ""),
                "category": row.get("category", ""),
                "price_100g": float(row.get("price_100g", 15000.0)),
                "source_name": row.get("source_name", ""),
                "source_priority": int(row.get("source_priority", 1)),
                "tags": row.get("tags") or set(),
                "energy_kcal": float(row.get("energy_kcal", 0.0)),
                "protein_g": float(row.get("protein_g", 0.0)),
                "fat_g": float(row.get("fat_g", 0.0)),
                "carbs_g": float(row.get("carbs_g", 0.0)),
            }
            metadata.append(item)
            
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

    def get_food_details(self, food_ids: list[int]) -> list[dict[str, Any]]:
        """Load full food records for a list of food_ids."""
        if not food_ids:
            return []

        query = """
            SELECT 
                f.food_id, f.canonical_key, f.canonical_name_en, f.name_vi,
                n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g,
                COALESCE(f.price_100g_vnd, 15000) AS price_100g,
                g.group_code AS category,
                f.source_name, f.source_priority,
                f.tags
            FROM foods f
            JOIN food_nutrients n ON f.food_id = n.food_id
            JOIN food_groups g ON f.food_group_id = g.food_group_id
            WHERE f.food_id = ANY(%s) AND f.is_active = TRUE;
        """

        foods_list = []
        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (food_ids,))
                    for row in cur.fetchall():
                        fid, key, name_en, name_vi, cal, prot, fat, carb, price, category, src_name, src_priority, tags_array = row
                        foods_list.append({
                            "food_id": int(fid),
                            "canonical_key": key,
                            "canonical_name_en": name_en,
                            "name_vi": name_vi,
                            "calories": float(cal or 0),
                            "protein": float(prot or 0),
                            "fat": float(fat or 0),
                            "carbs": float(carb or 0),
                            "cost_vnd_100g": float(price or 15000),
                            "category": category,
                            "source_name": src_name,
                            "source_priority": int(src_priority or 1),
                            "tags": set(tags_array) if tags_array else set(),
                        })
            return foods_list
        except Exception:
            # Fallback using snapshot metadata
            try:
                snapshot = self.load_cached_features("food_feature_snapshot")
                foods_list = []
                for item in snapshot["metadata"]:
                    if int(item["food_id"]) in food_ids:
                        foods_list.append({
                            "food_id": int(item["food_id"]),
                            "canonical_key": item.get("canonical_key", ""),
                            "canonical_name_en": item.get("canonical_name_en", ""),
                            "name_vi": item.get("name_vi", ""),
                            "calories": float(item.get("energy_kcal", 0.0)),
                            "protein": float(item.get("protein_g", 0.0)),
                            "fat": float(item.get("fat_g", 0.0)),
                            "carbs": float(item.get("carbs_g", 0.0)),
                            "cost_vnd_100g": float(item.get("price_100g", 15000.0)),
                            "category": item.get("category", ""),
                            "source_name": item.get("source_name", ""),
                            "source_priority": int(item.get("source_priority", 1)),
                            "tags": item.get("tags") or set(),
                        })
                return foods_list
            except Exception:
                return []