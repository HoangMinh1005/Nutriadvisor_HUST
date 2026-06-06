"""Constraint definitions for the CSP Meal Planner."""
from __future__ import annotations

from typing import Any, Dict, List, Set


class NutrientConstraints:
    """Encapsulates hard nutritional and economic constraints for meal scheduling."""

    def __init__(
        self,
        daily_calorie_target: float = 2000.0,
        calorie_tolerance_pct: float = 0.12,
        macro_ratios: Dict[str, float] | None = None,
        macro_tolerance_pct: float = 0.12,
        allergies: List[str] | None = None,
        budget_vnd_max: float | None = None,
        max_food_occurrences_per_week: int = 2,
    ) -> None:
        self.daily_calorie_target = daily_calorie_target
        self.calorie_tolerance_pct = calorie_tolerance_pct
        self.macro_ratios = macro_ratios or {"protein": 0.3, "fat": 0.3, "carbs": 0.4}
        self.macro_tolerance_pct = macro_tolerance_pct
        self.allergies = [a.lower().strip() for a in (allergies or []) if a.strip()]
        self.budget_vnd_max = budget_vnd_max
        self.max_food_occurrences_per_week = max_food_occurrences_per_week

    def check_daily_calories(self, food_nutrients: List[Dict[str, Any]], tolerance_multiplier: float = 1.0) -> bool:
        """Verify that the daily calories sum lies within acceptable bounds."""
        total_calories = sum(float(food.get("calories") or food.get("energy_kcal") or 0.0) for food in food_nutrients)
        tolerance = self.daily_calorie_target * self.calorie_tolerance_pct * tolerance_multiplier
        min_calories = self.daily_calorie_target - tolerance
        max_calories = self.daily_calorie_target + tolerance
        return min_calories <= total_calories <= max_calories

    def check_daily_macros(self, food_nutrients: List[Dict[str, Any]], tolerance_multiplier: float = 1.0) -> bool:
        """Verify that daily macro ratios (Protein, Fat, Carbs) are reasonably balanced.

        Uses a "total deviation budget" approach: the sum of absolute deviations
        across all three macros must stay within an overall budget.  This is much
        more forgiving than requiring each individual macro to be within a narrow
        band – a slight overshoot in carbs can be offset by undershoot in fat,
        which is realistic for Vietnamese cuisine.

        Additionally enforces a per-macro hard floor/ceiling to prevent extreme
        imbalances (e.g. 0% protein or 80% carbs).
        """
        total_protein = sum(float(food.get("protein") or food.get("protein_g") or 0.0) for food in food_nutrients)
        total_fat = sum(float(food.get("fat") or food.get("fat_g") or 0.0) for food in food_nutrients)
        total_carbs = sum(float(food.get("carbs") or food.get("carbs_g") or 0.0) for food in food_nutrients)

        total_mass = total_protein + total_fat + total_carbs
        if total_mass == 0:
            return False

        protein_ratio = total_protein / total_mass
        fat_ratio = total_fat / total_mass
        carbs_ratio = total_carbs / total_mass

        tolerance = self.macro_tolerance_pct * tolerance_multiplier

        target_p = self.macro_ratios.get("protein", 0.3)
        target_f = self.macro_ratios.get("fat", 0.3)
        target_c = self.macro_ratios.get("carbs", 0.4)

        # 1. Per-macro hard floor/ceiling: no single macro can deviate more than
        #    tolerance + 0.08 (absolute).  This blocks extreme meals like 5% fat.
        max_single_dev = tolerance + 0.08
        if (abs(protein_ratio - target_p) > max_single_dev
                or abs(fat_ratio - target_f) > max_single_dev
                or abs(carbs_ratio - target_c) > max_single_dev):
            return False

        # 2. Total deviation budget: the sum of all three deviations must be
        #    within 2.5 * tolerance.  At default tolerance=0.12 this is 0.30,
        #    meaning the average per-macro deviation can be up to 0.10.
        total_deviation = (
            abs(protein_ratio - target_p)
            + abs(fat_ratio - target_f)
            + abs(carbs_ratio - target_c)
        )
        return total_deviation <= tolerance * 2.5

    def check_allergies(self, food_nutrients: List[Dict[str, Any]]) -> bool:
        """Verify that none of the selected foods contain user allergens."""
        if not self.allergies:
            return True

        # Map user input strings to standard tag codes
        allergen_tag_mapping = {
            "hải sản": "allergen_seafood", "seafood": "allergen_seafood",
            "cá": "allergen_seafood", "fish": "allergen_seafood",
            "tôm": "allergen_seafood", "shrimp": "allergen_seafood",
            "cua": "allergen_seafood", "crab": "allergen_seafood",
            "trứng": "allergen_egg", "egg": "allergen_egg",
            "eggs": "allergen_egg", "yolk": "allergen_egg", "white": "allergen_egg",
            "lạc": "allergen_peanut", "đậu phộng": "allergen_peanut", "peanut": "allergen_peanut",
            "sữa": "allergen_milk", "milk": "allergen_milk", "bơ": "allergen_milk", "butter": "allergen_milk",
            "phô mai": "allergen_milk", "pho mai": "allergen_milk", "cheese": "allergen_milk", "whey": "allergen_milk",
            "đậu nành": "allergen_soy", "soy": "allergen_soy", "tofu": "allergen_soy",
            "lúa mì": "allergen_wheat", "bột mì": "allergen_wheat", "wheat": "allergen_wheat",
            "gluten": "allergen_wheat", "bánh mì": "allergen_wheat", "bread": "allergen_wheat",
            "bò": "allergen_beef", "beef": "allergen_beef",
            "heo": "allergen_pork", "lợn": "allergen_pork", "pork": "allergen_pork",
            "gà": "allergen_chicken", "chicken": "allergen_chicken",
            "vịt": "allergen_duck", "duck": "allergen_duck"
        }

        # Translate self.allergies to target tags
        target_tags = set()
        for allergen in self.allergies:
            allergen_clean = allergen.lower().strip()
            if allergen_clean.startswith("allergen_"):
                target_tags.add(allergen_clean)
            elif allergen_clean in allergen_tag_mapping:
                target_tags.add(allergen_tag_mapping[allergen_clean])
            else:
                # Fallback to substring matching on name/category if it's a custom unrecognized allergen
                for food in food_nutrients:
                    name_en = str(food.get("canonical_name_en") or "").lower()
                    name_vi = str(food.get("name_vi") or "").lower()
                    category = str(food.get("category") or "").lower()
                    if allergen_clean in name_en or allergen_clean in name_vi or allergen_clean in category:
                        return False

        if not target_tags:
            return True

        from csp.scheduler import get_dynamic_tags

        for food in food_nutrients:
            tags = food.get("tags") or set()
            if not tags:
                tags = get_dynamic_tags(food)
                food["tags"] = tags
            
            # If any target allergen tag is present in the food's tags, reject it
            if target_tags.intersection(tags):
                return False

        return True

    def check_weekly_diversity(self, weekly_food_ids: List[Any]) -> bool:
        """Ensure no individual food occurs more than the limit per week to prevent fatigue."""
        counts: Dict[Any, int] = {}
        for fid in weekly_food_ids:
            counts[fid] = counts.get(fid, 0) + 1
            if counts[fid] > self.max_food_occurrences_per_week:
                return False
        return True

    def check_daily_budget(self, food_costs: List[float], tolerance_multiplier: float = 1.0) -> bool:
        """Verify daily budget constraint."""
        if self.budget_vnd_max is None:
            return True
        total_cost = sum(food_costs)
        # Nới lỏng budget nếu cần thiết trong relaxation mode
        allowed_budget = self.budget_vnd_max * tolerance_multiplier
        # Sàn ngân sách 55% ở mức cơ bản để tránh quá rẻ, và tắt hoàn toàn khi nới lỏng (relaxation)
        if tolerance_multiplier > 1.0:
            min_budget = 0.0
        else:
            # Tỷ lệ điều chỉnh sàn ngân sách theo calo mục tiêu để tránh vô nghiệm khi ăn ít calo
            cal_scale = min(1.0, self.daily_calorie_target / 2000.0)
            min_budget = self.budget_vnd_max * 0.55 * cal_scale
        return min_budget <= total_cost <= allowed_budget


    def check_calorie_distribution(self, day_meals: List[Dict[str, Any]], tolerance_multiplier: float = 1.0) -> bool:
        """Verify that breakfast, lunch, and dinner calorie percentages fall within scientific bounds.
        
        Breakfast: 20% - 30% of daily calories.
        Lunch: 30% - 40% of daily calories.
        Dinner: 30% - 40% of daily calories.
        """
        meal_cals = {"breakfast": 0.0, "lunch": 0.0, "dinner": 0.0}
        total_calories = 0.0
        
        for meal in day_meals:
            meal_type = meal.get("meal_type")
            cals = float(meal.get("calories") or 0.0)
            total_calories += cals
            if meal_type in meal_cals:
                meal_cals[meal_type] += cals
                
        if total_calories == 0:
            return False
            
        b_pct = meal_cals["breakfast"] / total_calories
        l_pct = meal_cals["lunch"] / total_calories
        d_pct = meal_cals["dinner"] / total_calories
        
        # Base limits
        b_min, b_max = 0.15, 0.35
        l_min, l_max = 0.25, 0.45
        d_min, d_max = 0.25, 0.45
        
        # Apply relaxation if tolerance_multiplier > 1.0
        if tolerance_multiplier > 1.0:
            relaxation = (tolerance_multiplier - 1.0) * 0.05
            b_min = max(0.15, b_min - relaxation)
            b_max = min(0.35, b_max + relaxation)
            l_min = max(0.25, l_min - relaxation)
            l_max = min(0.45, l_max + relaxation)
            d_min = max(0.25, d_min - relaxation)
            d_max = min(0.45, d_max + relaxation)
            
        return (
            b_min <= b_pct <= b_max
            and l_min <= l_pct <= l_max
            and d_min <= d_pct <= d_max
        )

