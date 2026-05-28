"""Typed schema models for feature store outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np


@dataclass(slots=True)
class FoodFeatureVector:
    """Normalized 14D feature vector per food."""

    food_id: int
    canonical_key: str
    canonical_name_en: str
    energy_kcal_norm: float
    protein_g_norm: float
    fat_g_norm: float
    carbs_g_norm: float
    vitamin_a_mcg_norm: float
    beta_carotene_mcg_norm: float
    vitamin_c_mg_norm: float
    calcium_mg_norm: float
    iron_mg_norm: float
    zinc_mg_norm: float
    sodium_mg_norm: float
    cholesterol_mg_norm: float
    magnesium_mg_norm: float
    transfat_mg_norm: float
    vector: np.ndarray = field(repr=False)


@dataclass(slots=True)
class UserProfile:
    """User profile used by downstream ML modules."""

    user_id: int
    age: int
    gender: str
    weight_kg: float
    height_cm: float
    daily_calorie_target: float
    macro_ratios: dict[str, float]
    allergies: list[str]
    dietary_preferences: list[str]
    health_goal: str


@dataclass(slots=True)
class MealPlanRequest:
    """Request payload for meal planning."""

    user_id: int
    query: str
    user_profile: UserProfile
    num_days: int = 7
    num_meals_per_day: int = 4
    created_at: datetime = field(default_factory=datetime.utcnow)