"""Integration tests for the MealPlanPipeline."""

from __future__ import annotations

import os
import pytest

from backend.app.services.meal_plan_pipeline import MealPlanPipeline


def test_pipeline_smoke_offline(tmp_path) -> None:
    # Use a dummy DATABASE_URL to satisfy FeatureStore constructor check
    db_url = "postgresql://dummy"
    pipeline = MealPlanPipeline(db_url=db_url, cache_dir=tmp_path)
    
    # 1. Create a dummy features file so build_snapshot works in offline/test environment
    # Let's seed features snapshot using mock data
    from backend.ml.feature_store import FEATURE_COLUMNS, NUTRIENT_COLUMNS
    import numpy as np
    import pandas as pd
    
    raw_data = [
        # energy, protein, fat, carbs, ...
        [165.0, 31.0, 3.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # 1: Chicken Breast
        [389.0, 16.9, 6.9, 66.3, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], # 2: Oats
        [25.0, 1.3, 0.1, 5.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],    # 3: Cabbage
        [155.0, 13.0, 11.0, 1.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # 4: Egg
        [208.0, 20.0, 13.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # 5: Salmon
        [60.0, 3.2, 3.25, 4.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 6: Milk
        [89.0, 1.1, 0.3, 22.8, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 7: Banana
        [250.0, 26.0, 15.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],  # 8: Beef
        [130.0, 2.7, 0.3, 28.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 9: White Rice
        [50.0, 1.0, 0.1, 12.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],   # 10: Apple
    ]
    columns = [
        "energy_kcal", "protein_g", "fat_g", "carbs_g",
        "vitamin_a_mcg", "beta_carotene_mcg", "vitamin_c_mg", "calcium_mg",
        "iron_mg", "zinc_mg", "sodium_mg", "cholesterol_mg",
        "magnesium_mg", "transfat_mg"
    ]
    raw_df = pd.DataFrame(raw_data, columns=columns)
    raw_df["food_id"] = list(range(1, 11))
    raw_df["canonical_key"] = ["chicken", "oats", "cabbage", "egg", "salmon", "milk", "banana", "beef", "rice", "apple"]
    raw_df["canonical_name_en"] = ["Chicken", "Oats", "Cabbage", "Egg", "Salmon", "Milk", "Banana", "Beef", "Rice", "Apple"]
    raw_df["name_vi"] = ["ức gà", "yến mạch", "rau cải", "trứng", "cá hồi", "sữa tươi", "chuối", "thịt bò", "cơm trắng", "táo"]
    raw_df["category"] = ["gia_cam", "tinh_bot", "rau_cu", "trung_bo", "hai_san", "sua_che_pham", "trai_cay", "thit_bo", "tinh_bot", "trai_cay"]
    raw_df["price_100g"] = [15000.0] * 10
    raw_df["source_priority"] = [1] * 10
    raw_df["source_name"] = ["NIN"] * 10
    
    # Normalize nutrients
    normalized = pipeline.feature_store.normalize_nutrients(raw_df)
    matrix, metadata = pipeline.feature_store.to_feature_matrix(normalized)
    
    snapshot = {
        "raw": raw_df,
        "normalized": normalized,
        "matrix": matrix,
        "metadata": metadata,
        "feature_columns": list(FEATURE_COLUMNS),
        "nutrient_columns": list(NUTRIENT_COLUMNS),
    }
    
    pipeline.feature_store.cache_features("food_feature_snapshot", snapshot)
    
    # 2. Test initialization (loads mock snapshot and fits KNN)
    pipeline.initialize()
    assert pipeline._fitted is True
    
    # 3. Test generate_meal_plan
    user_profile = {
        "daily_calorie_target": 1500,
        "macro_ratios": {"protein": 0.35, "fat": 0.25, "carbs": 0.40},
        "budget_vnd_max": 200000,
        "exclude_snacks": True,
        "allergies": ["seafood"],
    }
    
    # Intercept scheduler to verify candidate foods are being passed correctly
    plan = pipeline.generate_meal_plan(user_profile)
    assert plan["feasible"] is True
    assert len(plan["meal_plan"]) == 7
    
    # Check that salmon (ID 5) was excluded from all meals
    for day in plan["meal_plan"]:
        for meal in day["meals"]:
            assert 5 not in meal.get("component_food_ids", [])
            assert meal["food_id"] != 5

    # 4. Test find_replacement
    replacements = pipeline.find_replacement(food_id=1, user_profile=user_profile, n=2)
    assert len(replacements) <= 2
    for r in replacements:
        assert r["food_id"] != 1
