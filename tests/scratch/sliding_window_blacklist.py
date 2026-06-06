import os
import sys
import random
import dotenv
from collections import Counter
from constraint import Problem

# Add current directory to path to load csp package
sys.path.insert(0, ".")
dotenv.load_dotenv()

from csp import MealScheduler
from csp.scheduler import get_dynamic_tags, clean_category
from csp.constraints import NutrientConstraints
from csp.objective import score_meal_plan

def run_single_day_csp(
    scheduler: MealScheduler,
    eligible_foods: list[dict],
    target_calories: float,
    target_budget: float,
    allergies: list[str],
    day: int,
    scheduled_plan: list[dict]
) -> list[dict] | None:
    """Finds breakfast, lunch, and dinner using the scheduler's multi-component scaling and recency penalty.
    
    Partitions the filtered eligible foods list into protein, carb, and fiber pools,
    solves the core variable combinations, and uses the scheduler's scaling algorithm
    to compile complete, calorie-balanced daily meals.
    """
    prob = Problem()
    
    # 1. Partition eligible foods into Carb, Protein, Fiber, and Snack pools
    all_carbs = []
    all_proteins = []
    all_fibers = []
    all_snacks = []
    
    def carb_priority_rank(x):
        name = str(x.get("name_vi") or x.get("canonical_name_en") or "").lower()
        if "cơm" in name or "com" in name:
            return 1
        if any(k in name for k in ["xôi", "xoi", "bún", "bun", "miến", "mien", "phở", "pho", "bánh mì", "banh mi"]):
            return 2
        return 3

    for f in eligible_foods:
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
            
        cat_clean = clean_category(f.get("category"))
        if any(c in cat_clean for c in ("trai_cay", "sua_che_pham", "hat", "do_an_vat")) or "is_dessert_snack" in tags:
            all_snacks.append(f)

    # Sort pools for priority and database preference
    all_carbs.sort(key=lambda x: (carb_priority_rank(x), int(x.get("source_priority") or 1)))
    all_proteins.sort(key=lambda x: int(x.get("source_priority") or 1))
    all_fibers.sort(key=lambda x: int(x.get("source_priority") or 1))
    all_snacks.sort(key=lambda x: int(x.get("source_priority") or 1))

    # 2. Build domain variables
    breakfast_candidates = []
    lunch_candidates = []
    dinner_candidates = []
    
    food_ids = [f["food_id"] for f in eligible_foods]
    
    for f in eligible_foods:
        fid = int(f["food_id"])
        tags = f.get("tags") or set()
        cat_clean = clean_category(f.get("category"))
        is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
        
        if "is_main_dish" in tags:
            if not is_snack:
                breakfast_candidates.append(fid)
                lunch_candidates.append(fid)
                dinner_candidates.append(fid)
        else:
            if not is_snack:
                if "allergen_egg" in tags or "role_carb" in tags or "allergen_milk" in tags or "role_fiber" in tags:
                    breakfast_candidates.append(fid)
                if "role_protein" in tags or "role_carb" in tags or "role_fiber" in tags:
                    lunch_candidates.append(fid)
                    dinner_candidates.append(fid)
                    
    fallback_ids = [fid for fid in food_ids]
    if not breakfast_candidates: breakfast_candidates = fallback_ids
    if not lunch_candidates: lunch_candidates = fallback_ids
    if not dinner_candidates: dinner_candidates = fallback_ids
    
    # Keep database order to ensure a healthy mix of carbs, proteins, and fibers
    # Shuffle capped domains so the solver explores diverse combinations randomly, avoiding DFS local traps
    import random
    rng = random.Random(42 + day)
    
    breakfast_candidates = list(breakfast_candidates)
    lunch_candidates = list(lunch_candidates)
    dinner_candidates = list(dinner_candidates)
    
    # Prioritize foods with source_priority = 1 (NIN database)
    breakfast_candidates.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    lunch_candidates.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    dinner_candidates.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    
    MAX_C = 120
    breakfast_candidates = breakfast_candidates[:MAX_C]
    lunch_candidates = lunch_candidates[:MAX_C]
    dinner_candidates = dinner_candidates[:MAX_C]
    
    rng.shuffle(breakfast_candidates)
    rng.shuffle(lunch_candidates)
    rng.shuffle(dinner_candidates)
    
    prob.addVariable("breakfast", breakfast_candidates)
    prob.addVariable("lunch", lunch_candidates)
    prob.addVariable("dinner", dinner_candidates)
    
    constraints = NutrientConstraints(
        daily_calorie_target=target_calories,
        calorie_tolerance_pct=0.12,
        macro_ratios={"protein": 0.30, "fat": 0.30, "carbs": 0.40},
        macro_tolerance_pct=0.12,
        allergies=allergies,
        budget_vnd_max=target_budget,
    )
    
    # Add a healthy combination check to guarantee balanced food selections
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
    
    solutions = prob.getSolutionIter()
    
    valid_scored = []
    checked_count = 0
    fail_reasons = {"calories": 0, "macros_hard": 0, "budget": 0, "exception": 0}
    for sol in solutions:
        if checked_count >= 4000: # Evaluate the entire priority combinations space
            break
        checked_count += 1
        
        try:
            # Call the scheduler's multi-component assembler & weight scaler
            day_meals = scheduler._get_meal_plan_for_solution(
                sol, constraints, 1.0,
                all_carbs, all_proteins, all_fibers, all_snacks
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
            
            # Score this daily meal plan
            base_score = score_meal_plan([{"meals": day_meals}], None, None)
            penalty = 0.0
            
            # A) Macro deviation penalty (soft)
            total_protein = sum(float(m.get("protein") or 0) for m in day_meals)
            total_fat = sum(float(m.get("fat") or 0) for m in day_meals)
            total_carbs_val = sum(float(m.get("carbs") or 0) for m in day_meals)
            total_mass = total_protein + total_fat + total_carbs_val
            if total_mass > 0:
                target_p = constraints.macro_ratios.get("protein", 0.3)
                target_f = constraints.macro_ratios.get("fat", 0.3)
                target_c = constraints.macro_ratios.get("carbs", 0.4)
                p_dev = abs(total_protein / total_mass - target_p)
                f_dev = abs(total_fat / total_mass - target_f)
                c_dev = abs(total_carbs_val / total_mass - target_c)
                total_dev = p_dev + f_dev + c_dev
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
                if b_pct < 0.15 or b_pct > 0.35:
                    penalty += abs(b_pct - 0.25) * 300.0
                if l_pct < 0.25 or l_pct > 0.45:
                    penalty += abs(l_pct - 0.35) * 300.0
                if d_pct < 0.25 or d_pct > 0.45:
                    penalty += abs(d_pct - 0.35) * 300.0
            
            # C) Recency Penalty
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
                if day >= 2:
                    prev_1_meals = scheduled_plan[-1]["meals"]
                    prev_1_ids = set()
                    for pm in prev_1_meals:
                        prev_1_ids.update(pm.get("component_food_ids", [pm["food_id"]]))
                    if fid in prev_1_ids:
                        penalty += 150.0
                        
                # 2 days ago
                if day >= 3:
                    prev_2_meals = scheduled_plan[-2]["meals"]
                    prev_2_ids = set()
                    for pm in prev_2_meals:
                        prev_2_ids.update(pm.get("component_food_ids", [pm["food_id"]]))
                    if fid in prev_2_ids:
                        penalty += 50.0
                        
                # 3 days ago
                if day >= 4:
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
            # print(f"DEBUG: exception {e}")
            continue
            
    if not valid_scored:
        print(f"Diagnostics for failure on Day {day}: Checked {checked_count} solutions. Fails: {fail_reasons}")
        
    if valid_scored:
        valid_scored.sort(key=lambda x: x[0], reverse=True)
        return valid_scored[0][2]
    return None

def generate_7_day_menu(database: list[dict], user_profile: dict) -> dict | None:
    """Manages the 7-day loop with a soft recency penalty and daily solver."""
    target_calories = user_profile.get("daily_calorie_target", 2200)
    target_budget = user_profile.get("budget_vnd_max", 200000)
    allergies = user_profile.get("allergies", [])
    
    # Initialize MealScheduler wrapper internally
    scheduler = MealScheduler(user_profile=user_profile, available_foods=database, db_url="")
    
    # Pre-filter foods violating allergy constraints
    from csp.constraints import NutrientConstraints
    nc = NutrientConstraints(allergies=allergies)
    allergy_filtered_db = [f for f in database if nc.check_allergies([f])]
    
    # Global frequency counting for the week
    used_food_ids = []
    
    print(f"=============================================================")
    print(f"KHỞI ĐẦU CHƯƠNG TRÌNH LẬP LỊCH 7 NGÀY (RECENCY DECAY PENALTY)")
    print(f"=============================================================")
    print(f"Calo mục tiêu: {target_calories} kcal | Ngân sách: {target_budget:,} VND")
    print(f"Dị ứng: {allergies}\n")
    
    scheduled_menu = {}
    scheduled_plan = []
    
    for day in range(1, 8):
        global_counts = Counter(used_food_ids)
        
        # Hard check: filter out foods already consumed >= 3 times this week
        eligible_foods = []
        for f in allergy_filtered_db:
            fid = int(f["food_id"])
            name = str(f.get("name_vi") or f.get("canonical_name_en") or "").lower()
            is_com = "cơm" in name or "com" in name
            if not is_com and global_counts[fid] >= 3:
                continue
            eligible_foods.append(f)
            
        print(f"--- NGÀY {day} ---")
        print(f"  Số lượng món ăn khả dụng sau lọc tần suất tuần: {len(eligible_foods)}")
        
        # Call Solver
        day_plan = run_single_day_csp(scheduler, eligible_foods, target_calories, target_budget, allergies, day, scheduled_plan)
        
        if day_plan:
            scheduled_plan.append({
                "day": day,
                "meals": day_plan,
            })
            scheduled_menu[day] = day_plan
            
            chosen_ids = []
            for m in day_plan:
                chosen_ids.extend(m.get("component_food_ids", [m["food_id"]]))
            used_food_ids.extend(chosen_ids)
            
            print(f"  [Thành công] Thực đơn được chọn ra cho ngày {day}:")
            for m in day_plan:
                print(f"    + {m['meal_type'].capitalize()}: {m['name']}")
            
            total_c = sum(m['calories'] for m in day_plan)
            total_p = sum(m['protein'] for m in day_plan)
            total_f = sum(m['fat'] for m in day_plan)
            total_carb = sum(m['carbs'] for m in day_plan)
            total_cost = sum(m['cost_vnd_100g'] for m in day_plan)
            print(f"    => Tổng: {total_c:.1f} kcal (P={total_p:.1f}g, F={total_f:.1f}g, C={total_carb:.1f}g) | Chi phí: {total_cost:,.0f} VND\n")
        else:
            print(f"=============================================================")
            print(f"KẾT THÚC: Thất bại tại ngày {day}")
            print(f"=============================================================")
            return None
            
    print(f"=============================================================")
    print(f"KẾT THÚC: Lập lịch 7 ngày thành công!")
    print(f"=============================================================")
    return scheduled_menu

if __name__ == "__main__":
    # Initialize MealScheduler to load database foods
    base_scheduler = MealScheduler(user_profile={})
    
    user_profile = {
        "daily_calorie_target": 2200,
        "budget_vnd_max": 200000,
        "allergies": ["seafood", "hải sản"],
        "exclude_snacks": True,
    }
    
    # Generate 7-day menu
    menu = generate_7_day_menu(base_scheduler.foods, user_profile)
