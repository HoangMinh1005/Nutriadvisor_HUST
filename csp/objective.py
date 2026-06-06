"""Objective functions for scoring meal planning solutions."""
from __future__ import annotations

from typing import Any, Dict, List


def score_meal_plan(
    meal_plan: List[Dict[str, Any]],
    maximize_nutrients: List[str] | None = None,
    minimize_nutrients: List[str] | None = None,
) -> float:
    """Evaluate and score a 7-day meal plan based on optimization objectives.

    Higher scores indicate higher quality plans.
    """
    score = 100.0
    max_nutrients = maximize_nutrients or []
    min_nutrients = minimize_nutrients or []

    for day_plan in meal_plan:
        meals = day_plan.get("meals", [])
        for meal in meals:
            # Check cost minimization
            cost = float(meal.get("cost_vnd_100g") or meal.get("price_100g") or 0.0)
            if "cost_vnd" in min_nutrients or "cost" in min_nutrients:
                # Deduct points for higher costs
                score -= cost * 0.001

            # Check nutrient maximization
            for nutrient in max_nutrients:
                val = float(meal.get(nutrient) or 0.0)
                # Gain points for maximizing desired nutrients (e.g. protein, calcium, magnesium)
                score += val * 1.5

            # Check nutrient minimization
            for nutrient in min_nutrients:
                if nutrient in ("cost_vnd", "cost"):
                    continue
                val = float(meal.get(nutrient) or 0.0)
                # Deduct points for higher values of minimized nutrients (e.g. fat, cholesterol, sodium)
                score -= val * 1.0

    return max(score, 0.0)
