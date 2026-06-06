import os
import sys
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, ".")

from csp import MealScheduler, NutrientConstraints
from csp.scheduler import get_dynamic_tags, clean_category, get_food_role, is_high_quality_protein

user_profile = {
    "daily_calorie_target": 2300,
    "macro_ratios": {"protein": 0.40, "fat": 0.30, "carbs": 0.30},
    "budget_vnd_max": 300000,
    "exclude_snacks": True,
    "allergies": ["seafood", "hải sản"],
}

scheduler = MealScheduler(user_profile=user_profile)

# Pre-partition foods
all_carbs = []
all_proteins = []
all_fibers = []
all_snacks = []
for f in scheduler.foods:
    tags = f.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(f)
        f["tags"] = tags
    if "role_protein" in tags:
        all_proteins.append(f)
    if "role_carb" in tags:
        all_carbs.append(f)
    if "role_fiber" in tags:
        all_fibers.append(f)

# Sort all_carbs using priority
def carb_priority_rank(x):
    name = str(x.get("name_vi") or x.get("canonical_name_en") or "").lower()
    if "cơm" in name or "com" in name:
        return 1
    if any(k in name for k in ["xôi", "xoi", "bún", "bun", "miến", "mien", "phở", "pho", "bánh mì", "banh mi"]):
        return 2
    return 3

all_carbs.sort(key=lambda x: (carb_priority_rank(x), int(x.get("source_priority") or 1)))
all_proteins.sort(key=lambda x: int(x.get("source_priority") or 1))
all_fibers.sort(key=lambda x: int(x.get("source_priority") or 1))

constraints = NutrientConstraints(
    daily_calorie_target=float(user_profile["daily_calorie_target"]),
    calorie_tolerance_pct=0.12,
    macro_ratios=user_profile["macro_ratios"],
    macro_tolerance_pct=0.12,
    allergies=user_profile["allergies"],
    budget_vnd_max=user_profile["budget_vnd_max"],
)

# Allergy pre-filter
domain_foods_all = [f for f in scheduler.foods if constraints.check_allergies([f])]

scheduled_plan = []
used_food_ids = []

from collections import Counter
from constraint import Problem
from csp.objective import score_meal_plan

for day in range(7):
    global_counts = Counter(used_food_ids)
    prev_day_ids = set()
    if scheduled_plan:
        for meal in scheduled_plan[-1]["meals"]:
            prev_day_ids.update(meal.get("component_food_ids", [meal["food_id"]]))
            
    # Filter domains dynamically
    breakfast_foods = []
    lunch_foods = []
    dinner_foods = []
    
    # Smarter domain selection
    for f in domain_foods_all:
        fid = int(f["food_id"])
        tags = f.get("tags") or set()
        cat_clean = clean_category(f.get("category"))
        is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
        
        if is_snack:
            continue
            
        # Diversity rules: Keep global occurrence limit of 3, but remove hard consecutive day check
        name = str(f.get("name_vi") or f.get("canonical_name_en") or "").lower()
        is_com = "cơm" in name or "com" in name
        
        if not is_com:
            # Exclude if used >= 3 times
            if global_counts[fid] >= 3:
                continue
                
        if "is_main_dish" in tags:
            breakfast_foods.append(fid)
            lunch_foods.append(fid)
            dinner_foods.append(fid)
        else:
            if "allergen_egg" in tags or "role_carb" in tags or "allergen_milk" in tags or "role_fiber" in tags:
                breakfast_foods.append(fid)
            if "role_protein" in tags or "role_carb" in tags or "role_fiber" in tags:
                lunch_foods.append(fid)
                dinner_foods.append(fid)

    # If domain is too small, fallback (relax the limit of 3 occurrences)
    if len(lunch_foods) < 5 or len(dinner_foods) < 5:
        breakfast_foods = []
        lunch_foods = []
        dinner_foods = []
        for f in domain_foods_all:
            fid = int(f["food_id"])
            tags = f.get("tags") or set()
            cat_clean = clean_category(f.get("category"))
            is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
            if is_snack: continue
            
            if "is_main_dish" in tags:
                breakfast_foods.append(fid)
                lunch_foods.append(fid)
                dinner_foods.append(fid)
            else:
                if "allergen_egg" in tags or "role_carb" in tags or "allergen_milk" in tags or "role_fiber" in tags:
                    breakfast_foods.append(fid)
                if "role_protein" in tags or "role_carb" in tags or "role_fiber" in tags:
                    lunch_foods.append(fid)
                    dinner_foods.append(fid)
                    
    # Keep database order to ensure a healthy mix of carbs, proteins, and fibers
    # Shuffle capped domains so the solver explores diverse combinations randomly, avoiding DFS local traps
    import random
    rng = random.Random(42 + day)
    
    breakfast_foods = list(breakfast_foods)
    lunch_foods = list(lunch_foods)
    dinner_foods = list(dinner_foods)
    
    # Prioritize foods with source_priority = 1 (NIN database)
    breakfast_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    lunch_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    dinner_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    
    MAX_C = 120
    breakfast_foods = breakfast_foods[:MAX_C]
    lunch_foods = lunch_foods[:MAX_C]
    dinner_foods = dinner_foods[:MAX_C]
    
    rng.shuffle(breakfast_foods)
    rng.shuffle(lunch_foods)
    rng.shuffle(dinner_foods)
    
    prob = Problem()
    prob.addVariable("breakfast", breakfast_foods)
    prob.addVariable("lunch", lunch_foods)
    prob.addVariable("dinner", dinner_foods)
    
    def check_daily_combination(b, l, d):
        b_food = scheduler.food_by_id[b]
        l_food = scheduler.food_by_id[l]
        d_food = scheduler.food_by_id[d]
        
        # 1. Allergy check
        if not constraints.check_allergies([b_food, l_food, d_food]):
            return False
            
        # 2. Nutrients check: Must have at least one carb source and one protein source among core foods
        has_carb = False
        has_protein = False
        
        for f in [b_food, l_food, d_food]:
            tags = f.get("tags") or set()
            if "is_main_dish" in tags:
                has_carb = True
                has_protein = True
            else:
                if "role_carb" in tags:
                    has_carb = True
                if "role_protein" in tags:
                    has_protein = True
                    
        if not has_carb or not has_protein:
            return False
            
        # 3. Variety check: Core lunch and dinner should not both be fibers or snacks
        l_tags = l_food.get("tags") or set()
        d_tags = d_food.get("tags") or set()
        
        l_is_light = "role_fiber" in l_tags or "is_dessert_snack" in l_tags
        d_is_light = "role_fiber" in d_tags or "is_dessert_snack" in d_tags
        if l_is_light and d_is_light:
            return False
            
        return True
        
    prob.addConstraint(check_daily_combination, ["breakfast", "lunch", "dinner"])
    
    sols = prob.getSolutionIter()
    
    # Score and choose
    valid_scored = []
    checked_count = 0
    fail_reasons = {"calories": 0, "macros_hard": 0, "budget": 0, "exception": 0}
    for sol in sols:
        if checked_count >= 2000: # Evaluate up to 2000 random combinations
            break
        checked_count += 1
        try:
            day_meals = scheduler._get_meal_plan_for_solution(
                sol, constraints, 1.0,
                all_carbs, all_proteins, all_fibers, []
            )
            # Hard constraints: calories & budget (non-negotiable)
            if not constraints.check_daily_calories(day_meals, 1.0):
                fail_reasons["calories"] += 1
                continue
            costs = [m["cost_vnd_100g"] for m in day_meals]
            if not constraints.check_daily_budget(costs, 1.0):
                fail_reasons["budget"] += 1
                continue

            # ---------- Soft penalties (never reject, just penalize) ----------
            
            # Base score
            base_score = score_meal_plan([{"meals": day_meals}], None, None)
            penalty = 0.0
            
            # A) Macro deviation penalty (soft)
            total_protein = sum(float(m.get("protein") or 0) for m in day_meals)
            total_fat = sum(float(m.get("fat") or 0) for m in day_meals)
            total_carbs = sum(float(m.get("carbs") or 0) for m in day_meals)
            total_mass = total_protein + total_fat + total_carbs
            if total_mass > 0:
                target_p = constraints.macro_ratios.get("protein", 0.3)
                target_f = constraints.macro_ratios.get("fat", 0.3)
                target_c = constraints.macro_ratios.get("carbs", 0.4)
                p_dev = abs(total_protein / total_mass - target_p)
                f_dev = abs(total_fat / total_mass - target_f)
                c_dev = abs(total_carbs / total_mass - target_c)
                total_dev = p_dev + f_dev + c_dev
                # Scale: 0.0 deviation = 0 penalty, 0.30 deviation = 150 penalty
                penalty += total_dev * 500.0
            
            # B) Calorie distribution penalty (soft)
            total_cal = sum(float(m.get("calories") or 0) for m in day_meals)
            if total_cal > 0:
                meal_cals = {"breakfast": 0.0, "lunch": 0.0, "dinner": 0.0}
                for m in day_meals:
                    mt = m.get("meal_type", "")
                    if mt in meal_cals:
                        meal_cals[mt] += float(m.get("calories") or 0)
                b_pct = meal_cals["breakfast"] / total_cal
                l_pct = meal_cals["lunch"] / total_cal
                d_pct = meal_cals["dinner"] / total_cal
                
                # Penalize extreme distribution (target: ~25/35/35)
                if b_pct < 0.15 or b_pct > 0.35:
                    penalty += abs(b_pct - 0.25) * 300.0
                if l_pct < 0.25 or l_pct > 0.45:
                    penalty += abs(l_pct - 0.35) * 300.0
                if d_pct < 0.25 or d_pct > 0.45:
                    penalty += abs(d_pct - 0.35) * 300.0
            
            # C) Recency penalty
            cand_ids = []
            for m in day_meals:
                cand_ids.extend(m.get("component_food_ids", [m["food_id"]]))
                
            for fid in cand_ids:
                f = scheduler.food_by_id[fid]
                name = str(f.get("name_vi") or f.get("canonical_name_en") or "").lower()
                is_com = ("cơm" in name or "com" in name) and ("mận" not in name)
                if is_com:
                    continue  # Rice is allowed daily without penalty
                
                # 1 day ago (Yesterday)
                if day >= 1:
                    prev_1_meals = scheduled_plan[-1]["meals"]
                    prev_1_ids = set()
                    for pm in prev_1_meals:
                        prev_1_ids.update(pm.get("component_food_ids", [pm["food_id"]]))
                    if fid in prev_1_ids:
                        penalty += 150.0
                        
                # 2 days ago
                if day >= 2:
                    prev_2_meals = scheduled_plan[-2]["meals"]
                    prev_2_ids = set()
                    for pm in prev_2_meals:
                        prev_2_ids.update(pm.get("component_food_ids", [pm["food_id"]]))
                    if fid in prev_2_ids:
                        penalty += 50.0
                        
                # 3 days ago
                if day >= 3:
                    prev_3_meals = scheduled_plan[-3]["meals"]
                    prev_3_ids = set()
                    for pm in prev_3_meals:
                        prev_3_ids.update(pm.get("component_food_ids", [pm["food_id"]]))
                    if fid in prev_3_ids:
                        penalty += 20.0
            
            final_score = base_score - penalty
            valid_scored.append((final_score, sol, day_meals))
        except Exception as e:
            fail_reasons["exception"] += 1
            continue
            
    if not valid_scored:
        print(f"Diagnostics for failure on Day {day+1}: Checked {checked_count} solutions. Fails: {fail_reasons}")
        # Print details of first few solutions to see what's failing
        print("First 5 failing solutions details:")
        debug_count = 0
        for sol in sols:
            if debug_count >= 5:
                break
            try:
                day_meals = scheduler._get_meal_plan_for_solution(
                    sol, constraints, 1.0,
                    all_carbs, all_proteins, all_fibers, []
                )
                total_cal = sum(float(food.get("calories") or food.get("energy_kcal") or 0.0) for food in day_meals)
                total_protein = sum(float(food.get("protein") or food.get("protein_g") or 0.0) for food in day_meals)
                total_fat = sum(float(food.get("fat") or food.get("fat_g") or 0.0) for food in day_meals)
                total_carbs = sum(float(food.get("carbs") or food.get("carbs_g") or 0.0) for food in day_meals)
                total_mass = total_protein + total_fat + total_carbs
                p_ratio = total_protein / total_mass if total_mass > 0 else 0
                f_ratio = total_fat / total_mass if total_mass > 0 else 0
                c_ratio = total_carbs / total_mass if total_mass > 0 else 0
                print(f"  Fail {debug_count+1}: {[scheduler.food_by_id[sol[k]]['name_vi'] for k in ['breakfast', 'lunch', 'dinner']]}")
                print(f"    Calories: {total_cal:.1f} (target {constraints.daily_calorie_target})")
                print(f"    P: {p_ratio:.3f} (target 0.3), F: {f_ratio:.3f} (target 0.3), C: {c_ratio:.3f} (target 0.4)")
                debug_count += 1
            except Exception as e:
                print(f"  Fail {debug_count+1}: exception {type(e).__name__}: {e}")
                debug_count += 1
        
    if valid_scored:
        valid_scored.sort(key=lambda x: x[0], reverse=True)
        best_sol = valid_scored[0]
        scheduled_plan.append({
            "day": day + 1,
            "meals": best_sol[2]
        })
        cand_ids = []
        for m in best_sol[2]:
            cand_ids.extend(m.get("component_food_ids", [m["food_id"]]))
        used_food_ids.extend(cand_ids)
    else:
        print(f"FAILED on day {day+1}")
        break

# Print final plan
for day_plan in scheduled_plan:
    print(f"\n--- DAY {day_plan['day']} ---")
    for m in day_plan["meals"]:
        print(f"  {m['meal_type']}: {m['name']} | {m['calories']:.1f} kcal")
