"""Unit tests for the KNNFoodRecommender module."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.ml.recsys.knn_recommender import KNNFoodRecommender


def _mock_nutrient_data() -> tuple[np.ndarray, list[dict], pd.DataFrame]:
    # 10 foods with various nutrient densities
    # first 4 cols: energy_kcal, protein_g, fat_g, carbs_g
    raw_data = [
        # energy, protein, fat, carbs, ... + 10 other columns
        [165.0, 31.0, 3.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # 1: Chicken Breast (high protein)
        [389.0, 16.9, 6.9, 66.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], # 2: Oats (high carb)
        [25.0, 1.3, 0.1, 5.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],    # 3: Cabbage (fiber)
        [155.0, 13.0, 11.0, 1.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # 4: Egg (protein/fat, allergy egg)
        [208.0, 20.0, 13.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # 5: Salmon (protein/fat, allergy seafood)
        [60.0, 3.2, 3.25, 4.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 6: Milk (allergy milk)
        [89.0, 1.1, 0.3, 22.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 7: Banana (snack)
        [250.0, 26.0, 15.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # 8: Beef (protein/fat)
        [130.0, 2.7, 0.3, 28.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 9: White Rice (carb)
        [50.0, 1.0, 0.1, 12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 10: Apple (snack)
    ]

    columns = [
        "energy_kcal", "protein_g", "fat_g", "carbs_g",
        "vitamin_a_mcg", "beta_carotene_mcg", "vitamin_c_mg", "calcium_mg",
        "iron_mg", "zinc_mg", "sodium_mg", "cholesterol_mg",
        "magnesium_mg", "transfat_mg"
    ]

    raw_df = pd.DataFrame(raw_data, columns=columns)
    
    # Simple min-max normalization
    norm_data = []
    for col in columns:
        vals = raw_df[col]
        mn, mx = vals.min(), vals.max()
        if mx > mn:
            norm_data.append((vals - mn) / (mx - mn))
        else:
            norm_data.append(pd.Series([0.0] * len(vals)))
    
    feature_matrix = np.column_stack(norm_data).astype(np.float32)

    metadata = [
        {"food_id": 1, "canonical_key": "chicken_breast", "canonical_name_en": "Chicken Breast", "name_vi": "ức gà", "category": "gia_cam", "tags": {"role_protein", "clean_protein"}},
        {"food_id": 2, "canonical_key": "oats", "canonical_name_en": "Oats", "name_vi": "yến mạch", "category": "tinh_bot", "tags": {"role_carb"}},
        {"food_id": 3, "canonical_key": "cabbage", "canonical_name_en": "Cabbage", "name_vi": "rau cải", "category": "rau_cu", "tags": {"role_fiber"}},
        {"food_id": 4, "canonical_key": "egg", "canonical_name_en": "Egg", "name_vi": "trứng", "category": "trung_bo", "tags": {"allergen_egg", "role_protein"}},
        {"food_id": 5, "canonical_key": "salmon", "canonical_name_en": "Salmon", "name_vi": "cá hồi", "category": "hai_san", "tags": {"allergen_seafood", "role_protein"}},
        {"food_id": 6, "canonical_key": "milk", "canonical_name_en": "Milk", "name_vi": "sữa tươi", "category": "sua_che_pham", "tags": {"allergen_milk"}},
        {"food_id": 7, "canonical_key": "banana", "canonical_name_en": "Banana", "name_vi": "chuối", "category": "trai_cay", "tags": {"is_dessert_snack"}},
        {"food_id": 8, "canonical_key": "beef", "canonical_name_en": "Beef", "name_vi": "thịt bò", "category": "thit_bo", "tags": {"role_protein"}},
        {"food_id": 9, "canonical_key": "white_rice", "canonical_name_en": "White Rice", "name_vi": "cơm trắng", "category": "tinh_bot", "tags": {"role_carb"}},
        {"food_id": 10, "canonical_key": "apple", "canonical_name_en": "Apple", "name_vi": "táo", "category": "trai_cay", "tags": {"is_dessert_snack"}},
    ]

    # Add raw values to metadata to simulate extract_features output
    for i, meta in enumerate(metadata):
        meta["energy_kcal"] = raw_data[i][0]
        meta["protein_g"] = raw_data[i][1]
        meta["fat_g"] = raw_data[i][2]
        meta["carbs_g"] = raw_data[i][3]

    return feature_matrix, metadata, raw_df


def test_knn_fit():
    matrix, metadata, raw_df = _mock_nutrient_data()
    recommender = KNNFoodRecommender()
    recommender.fit(matrix, metadata, raw_df)

    assert recommender.feature_matrix is not None
    assert len(recommender.food_metadata) == 10
    assert recommender.min_values["energy_kcal"] == 25.0
    assert recommender.max_values["energy_kcal"] == 389.0


def test_knn_recommend_for_profile():
    matrix, metadata, raw_df = _mock_nutrient_data()
    recommender = KNNFoodRecommender()
    recommender.fit(matrix, metadata, raw_df)

    # User profile with high protein target
    user_profile = {
        "daily_calorie_target": 2000,
        "macro_ratios": {"protein": 0.50, "fat": 0.20, "carbs": 0.30},
        "allergies": ["egg"],  # exclude food 4 (Egg)
        "exclude_snacks": True,  # exclude foods 7, 10
    }

    candidates = recommender.recommend_for_profile(user_profile, n=5)

    # Should not include Egg (4), Banana (7), Apple (10)
    assert 4 not in candidates
    assert 7 not in candidates
    assert 10 not in candidates

    # Should return up to n candidates
    assert len(candidates) > 0
    # First item should be high-protein non-allergic (e.g. Chicken Breast - ID 1, or Beef - ID 8, or Salmon - ID 5)
    assert candidates[0] in [1, 5, 8]


def test_knn_recommend_similar():
    matrix, metadata, raw_df = _mock_nutrient_data()
    recommender = KNNFoodRecommender()
    recommender.fit(matrix, metadata, raw_df)

    # Chicken Breast is food_id 1
    similar = recommender.recommend_similar(food_id=1, n=3, exclude=[])
    assert len(similar) <= 3
    # Top similar to Chicken Breast should be high protein sources like Beef (8) or Salmon (5)
    similar_ids = [s["food_id"] for s in similar]
    assert 8 in similar_ids or 5 in similar_ids
    # Query food should be excluded
    assert 1 not in similar_ids


def test_knn_recommend_complementary():
    matrix, metadata, raw_df = _mock_nutrient_data()
    recommender = KNNFoodRecommender()
    recommender.fit(matrix, metadata, raw_df)

    # User target is protein: 0.4, fat: 0.3, carbs: 0.3 (total 2000 kcal)
    # Target in grams: protein = 200g, fat = 66g, carbs = 150g
    # Current selection: Oats (ID 2), which is high carb (carb=66.3g, protein=16.9g)
    # Deficit should be protein-heavy
    target_profile = {
        "daily_calorie_target": 2000,
        "macro_ratios": {"protein": 0.40, "fat": 0.30, "carbs": 0.30},
    }

    recs = recommender.recommend_complementary(
        current_food_ids=[2],
        target_profile=target_profile,
        n=3,
    )

    rec_ids = [r["food_id"] for r in recs]
    # Recommends should heavily prioritize high protein / fat to balance oats: e.g. Chicken (1), Salmon (5) or Beef (8)
    assert len(recs) > 0
    assert any(x in rec_ids for x in [1, 5, 8])
