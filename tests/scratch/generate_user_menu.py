import os
import sys
import dotenv

# Load environment variables (.env has DATABASE_URL)
dotenv.load_dotenv()

sys.path.insert(0, ".")
from csp import MealScheduler

# Build user profile for CSP Solver
user_profile = {
    "daily_calorie_target": 2200,
    "macro_ratios": {"protein": 0.30, "fat": 0.30, "carbs": 0.40},
    "budget_vnd_max": 200000,
    "exclude_snacks": True,  # 3 meals only (no snacks)
    "allergies": ["seafood", "hải sản"],
}

# Initialize Scheduler
scheduler = MealScheduler(user_profile=user_profile)
result = scheduler.solve_with_relaxation()

if result["feasible"]:
    print("SUCCESS")
    print(f"Relaxation attempts: {result['relaxation_attempts']}")
    print(f"Score: {result.get('score', 0)}")
    
    for day_idx, day_plan in enumerate(result["meal_plan"], start=1):
        total_calories = sum(m.get("calories", 0) for m in day_plan["meals"])
        total_protein = sum(m.get("protein", 0) for m in day_plan["meals"])
        total_fat = sum(m.get("fat", 0) for m in day_plan["meals"])
        total_carbs = sum(m.get("carbs", 0) for m in day_plan["meals"])
        estimated_cost_vnd = sum(m.get("cost_vnd_100g", 15000) for m in day_plan["meals"])
        
        print(f"--- DAY {day_idx} ---")
        print(f"Calories: {total_calories:.1f} kcal")
        print(f"Macros: P={total_protein:.1f}g | F={total_fat:.1f}g | C={total_carbs:.1f}g")
        print(f"Cost: {estimated_cost_vnd:,.0f} VND")
        
        b_cal = sum(m.get("calories", 0) for m in day_plan["meals"] if m["meal_type"] == "breakfast")
        l_cal = sum(m.get("calories", 0) for m in day_plan["meals"] if m["meal_type"] == "lunch")
        d_cal = sum(m.get("calories", 0) for m in day_plan["meals"] if m["meal_type"] == "dinner")
        print(f"Distribution: Breakfast={b_cal:.0f} kcal ({b_cal/total_calories*100:.0f}%) | Lunch={l_cal:.0f} kcal ({l_cal/total_calories*100:.0f}%) | Dinner={d_cal:.0f} kcal ({d_cal/total_calories*100:.0f}%)")
        
        print("Meals:")
        for meal in day_plan["meals"]:
            meal_type_vi = {
                "breakfast": "Bữa sáng",
                "lunch": "Bữa trưa",
                "dinner": "Bữa tối"
            }.get(meal["meal_type"], meal["meal_type"])
            print(f"  + {meal_type_vi}: {meal['name']} | {meal.get('calories', 0):.1f} kcal | {meal.get('cost_vnd_100g', 0):.0f} VND")
else:
    print("FAILED")
