import sys
import os
import logging
import traceback

logging.basicConfig(level=logging.INFO)
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from csp import MealScheduler

# Let's run only attempt 1 (multiplier=1.0) and inspect the first few exceptions in detail
original_get_meal_plan = MealScheduler._get_meal_plan_for_solution

exception_count = 0

def debug_get_meal_plan(self, sol, constraints, tolerance_multiplier, all_carbs, all_proteins, all_fibers, all_snacks, day_excluded_ids=None):
    global exception_count
    try:
        res = original_get_meal_plan(self, sol, constraints, tolerance_multiplier, all_carbs, all_proteins, all_fibers, all_snacks, day_excluded_ids)
        return res
    except Exception as e:
        if exception_count < 10:
            print("\nEXCEPTION IN _get_meal_plan_for_solution:")
            traceback.print_exc(file=sys.stdout)
            exception_count += 1
        raise

MealScheduler._get_meal_plan_for_solution = debug_get_meal_plan

user = {
    "daily_calorie_target": 1000,
    "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
    "allergies": ["duck", "vịt"],
    "budget_vnd_max": 100000,
}

scheduler = MealScheduler(user_profile=user, db_url="")
print("Running solve_with_relaxation...")
result = scheduler.solve_with_relaxation(max_attempts=1)
