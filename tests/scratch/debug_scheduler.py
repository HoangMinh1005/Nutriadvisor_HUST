import sys
import os

sys.path.insert(0, ".")

from csp import MealScheduler, NutrientConstraints
from csp.scheduler import classify_food

def test_debug():
    with open("tests/scratch/debug_output.txt", "w", encoding="utf-8") as out:
        user = {
            "daily_calorie_target": 1000,
            "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
            "allergies": ["duck", "vịt"],
            "budget_vnd_max": 100000,
        }
        
        try:
            scheduler = MealScheduler(user_profile=user, db_url="")
            out.write(f"Loaded {len(scheduler.foods)} foods from offline fallback.\n")
            
            # Count classifications
            from collections import Counter
            roles = Counter()
            for f in scheduler.foods:
                roles[classify_food(f)] += 1
            out.write(f"Classifications count: {dict(roles)}\n")
            
            # Print some foods that are role_fiber or category match and what role they got
            out.write("\nSample fiber foods:\n")
            fiber_count = 0
            for f in scheduler.foods:
                tags = f.get("tags") or set()
                if "role_fiber" in tags or "rau" in str(f.get("name_vi")).lower():
                    role = classify_food(f)
                    out.write(f"ID={f['food_id']} Name={f['name_vi']} Category={f['category']} Role={role} Tags={tags}\n")
                    fiber_count += 1
                    if fiber_count >= 20:
                        break
            
            # Try solving
            res = scheduler.solve_with_relaxation()
            out.write(f"Solver Result Feasible: {res['feasible']}\n")
            if not res["feasible"]:
                out.write(f"Relaxation attempts made: {res.get('relaxation_attempts')}\n")
        except Exception as e:
            import traceback
            out.write(f"Error occurred: {e}\n")
            traceback.print_exc(file=out)
        
if __name__ == "__main__":
    test_debug()
