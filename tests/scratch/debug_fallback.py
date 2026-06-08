import sys
sys.path.insert(0, ".")

from csp import MealScheduler
from csp.constraints import NutrientConstraints
from csp.classification import classify_food

user = {
    "daily_calorie_target": 1000,
    "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
    "allergies": ["duck", "vịt"],  # Duck has food_id=10
    "budget_vnd_max": 100000,
}

scheduler = MealScheduler(user_profile=user, db_url="")

# Let's inspect the classification roles of all foods
print("--- Food Roles ---")
for f in scheduler.foods:
    role = classify_food(f)
    print(f"Food {f['food_id']}: {f['name_vi']} -> Role: {role}, Cal: {f['calories']}, Prot: {f['protein']}, Fat: {f['fat']}, Carb: {f['carbs']}")

# Let's patch _solve to print debugging info
original_solve = scheduler._solve

def debug_solve(domain_foods, constraints, tolerance_multiplier):
    print(f"\n=== Running _solve with tolerance_multiplier={tolerance_multiplier} ===")
    food_roles_cache = {int(f["food_id"]): classify_food(f) for f in scheduler.foods}
    
    all_carbs = [x for x in scheduler.foods if food_roles_cache[int(x["food_id"])] == "STAPLE_CARB"]
    all_proteins = [x for x in scheduler.foods if food_roles_cache[int(x["food_id"])] == "MAIN_PROTEIN"]
    all_fibers = [x for x in scheduler.foods if food_roles_cache[int(x["food_id"])] == "FIBER_SIDE"]
    all_snacks = scheduler.foods

    exclude_snacks = scheduler.user.get("exclude_snacks", False)
    scheduled_plan = []
    used_food_ids = []
    offal_blood_count = 0

    for day in range(7):
        print(f"\n--- Day {day+1} ---")
        from collections import Counter
        global_counts = Counter(used_food_ids)
        print("Used foods so far:", global_counts)
        
        breakfast_foods = []
        lunch_foods = []
        dinner_foods = []
        snack_foods = []
        
        for f in domain_foods:
            fid = int(f["food_id"])
            role = food_roles_cache[fid]
            name_vi = str(f.get("name_vi") or "").lower()
            
            if role == "ACCESSORY_CONDIMENT":
                continue
            if global_counts[fid] >= 3 and not ("cơm" in name_vi or "com" in name_vi):
                continue
                
            is_valid_vietnamese_breakfast = any(k in name_vi for k in ["bún", "miến", "phở", "cháo", "xôi", "bánh mì", "bánh mỳ", "bánh cuốn"])
            is_snack_cake = any(k in name_vi for k in ["bánh nếp", "bánh trôi", "bánh chay", "bánh tẻ", "bánh gio", "bánh cốm", "bánh rán", "bánh đa nem", "bánh quẩy", "bánh mì, vuông, ngọt"])

            if is_valid_vietnamese_breakfast and not is_snack_cake:
                breakfast_foods.append(fid)
            if role == "MAIN_PROTEIN" and not is_snack_cake:
                lunch_foods.append(fid)
                dinner_foods.append(fid)
            snack_foods.append(fid)

        if not breakfast_foods:
            breakfast_foods = [x["food_id"] for x in scheduler.foods if food_roles_cache[int(x["food_id"])] == "STAPLE_CARB"][:30]
        if not lunch_foods:
            lunch_foods = [x["food_id"] for x in scheduler.foods if food_roles_cache[int(x["food_id"])] == "MAIN_PROTEIN"][:30]
        if not dinner_foods:
            dinner_foods = [x["food_id"] for x in scheduler.foods if food_roles_cache[int(x["food_id"])] == "MAIN_PROTEIN"][:30]

        print("Breakfast candidates:", breakfast_foods)
        print("Lunch candidates:", lunch_foods)
        print("Dinner candidates:", dinner_foods)

        from constraint import Problem
        prob = Problem()
        prob.addVariable("breakfast", list(set(breakfast_foods))[:50])
        prob.addVariable("lunch", list(set(lunch_foods))[:150])
        if not exclude_snacks:
            snack_candidates = list(set(snack_foods))[:50]
            prob.addVariable("snack", snack_candidates)
        prob.addVariable("dinner", list(set(dinner_foods))[:150])

        def check_inline_budget_and_habits(*args):
            b, l, d = args[0], args[1], args[-1]
            b_f, l_f, d_f = scheduler.food_by_id[b], scheduler.food_by_id[l], scheduler.food_by_id[d]
            if not constraints.check_allergies([b_f, l_f, d_f]):
                return False
            approx_cost = b_f.get("cost_vnd_100g", 15000) + l_f.get("cost_vnd_100g", 15000) + d_f.get("cost_vnd_100g", 15000)
            if approx_cost > constraints.budget_vnd_max:
                return False
            return True

        var_order = ["breakfast", "lunch", "snack", "dinner"] if not exclude_snacks else ["breakfast", "lunch", "dinner"]
        prob.addConstraint(check_inline_budget_and_habits, var_order)

        sols = list(prob.getSolutionIter())
        print(f"Total solutions from CSP: {len(sols)}")
        
        valid_scored = []
        failures = Counter()
        
        for sol in sols[:300]:
            try:
                day_meals = scheduler._get_meal_plan_for_solution(
                    sol, constraints, tolerance_multiplier,
                    all_carbs, all_proteins, all_fibers, all_snacks,
                    day_excluded_ids=set(used_food_ids),
                    cached_roles=food_roles_cache
                )
                
                if not constraints.check_daily_calories(day_meals, tolerance_multiplier):
                    failures["calories"] += 1
                    continue
                if not constraints.check_daily_macros(day_meals, tolerance_multiplier):
                    failures["macros"] += 1
                    continue
                if not constraints.check_daily_budget([m["cost_vnd_100g"] for m in day_meals], tolerance_multiplier):
                    failures["budget"] += 1
                    continue
                
                valid_scored.append((0, sol, day_meals))
            except Exception as e:
                failures[f"exception: {str(e)}"] += 1
                continue
        
        print(f"Valid scored solutions: {len(valid_scored)}")
        print(f"Failures summary: {dict(failures)}")
        
        if not valid_scored:
            print("Trying EMERGENCY RECOVERY BLOCK...")
            sols = prob.getSolutionIter()
            for sol in sols:
                try:
                    day_meals = scheduler._get_meal_plan_for_solution(
                        sol, constraints, tolerance_multiplier,
                        all_carbs, all_proteins, all_fibers, all_snacks,
                        day_excluded_ids=set(used_food_ids),
                        cached_roles=food_roles_cache
                    )
                    costs = [m["cost_vnd_100g"] for m in day_meals]
                    if sum(costs) <= constraints.budget_vnd_max and constraints.check_daily_calories(day_meals, tolerance_multiplier * 1.3):
                        total_p = sum(m["protein"] for m in day_meals)
                        total_m = total_p + sum(m["fat"] for m in day_meals) + sum(m["carbs"] for m in day_meals)
                        if total_m > 0:
                            actual_p_ratio = total_p / total_m
                            user_target_p = (scheduler.user.get("macro_ratios") or {}).get("protein", 0.30)
                            if (user_target_p - 0.04) <= actual_p_ratio <= (user_target_p + 0.05):
                                valid_scored.append((0, sol, day_meals))
                                break
                except Exception as e:
                    pass
            
            if valid_scored:
                print("Emergency recovery succeeded!")
            else:
                print("Emergency recovery failed!")
                return {"feasible": False, "meal_plan": []}

        best_day = valid_scored[0]
        scheduled_plan.append({"day": day + 1, "meals": best_day[2]})
        for m in best_day[2]:
            c_ids = m.get("component_food_ids", [m["food_id"]])
            used_food_ids.extend(c_ids)

    return {"feasible": True, "meal_plan": scheduled_plan}

scheduler._solve = debug_solve
res = scheduler.solve_with_relaxation()
print("\nFinal Result Feasible:", res["feasible"])
