import sys
sys.path.insert(0, ".")

from csp import MealScheduler, NutrientConstraints
from csp.classification import classify_food, get_dynamic_tags, clean_category, is_gym_blacklisted, is_offal_or_blood, is_single_bowl_meal
import random

class DiagnosticScheduler(MealScheduler):
    def _get_meal_plan_for_solution(self, sol, constraints, tolerance_multiplier, all_carbs, all_proteins, all_fibers, all_snacks, day_excluded_ids=None):
        # We copy the original _get_meal_plan_for_solution logic but print verbose info for Candidate 1 of Day 2
        from csp.classification import is_single_bowl_meal, is_clean_protein_gym, get_max_serving_g, get_food_role, is_standalone_main_dish
        
        # Helper to find a safe complementary item from a pool
        def get_complementary(pool, excluded_ids=None):
            if excluded_ids is None:
                excluded_ids = set()
            candidates = []
            for f in pool:
                fid = int(f["food_id"])
                if fid in excluded_ids:
                    continue
                if day_excluded_ids and fid in day_excluded_ids:
                    continue
                if not constraints.check_allergies([f]):
                    continue
                candidates.append(f)
            if candidates:
                import random
                limit = min(10, len(candidates))
                return random.choice(candidates[:limit])
            candidates_fallback = []
            for f in pool:
                fid = int(f["food_id"])
                if fid in excluded_ids:
                    continue
                if not constraints.check_allergies([f]):
                    continue
                candidates_fallback.append(f)
            if candidates_fallback:
                import random
                limit = min(10, len(candidates_fallback))
                return random.choice(candidates_fallback[:limit])
            return pool[0]

        def build_meal_components(core_food, slot, excluded_ids):
            components = []
            if is_single_bowl_meal(core_food):
                components.append({"slot": slot, "food": core_food, "role": "core"})
                core_role = classify_food(core_food)
                if core_role != "FIBER_SIDE":
                    comp_food = get_complementary(all_fibers, excluded_ids)
                    components.append({"slot": slot, "food": comp_food, "role": "fiber"})
                    excluded_ids.add(comp_food["food_id"])
            else:
                core_role = classify_food(core_food)
                components.append({"slot": slot, "food": core_food, "role": "core"})
                has_carb = (core_role == "STAPLE_CARB")
                has_protein = (core_role == "MAIN_PROTEIN")
                has_fiber = (core_role == "FIBER_SIDE")
                if not has_carb:
                    comp_food = get_complementary(all_carbs, excluded_ids)
                    components.append({"slot": slot, "food": comp_food, "role": "carb"})
                    excluded_ids.add(comp_food["food_id"])
                if not has_protein:
                    comp_food = get_complementary(comp_proteins_pool, excluded_ids)
                    components.append({"slot": slot, "food": comp_food, "role": "protein"})
                    excluded_ids.add(comp_food["food_id"])
                if not has_fiber:
                    comp_food = get_complementary(all_fibers, excluded_ids)
                    components.append({"slot": slot, "food": comp_food, "role": "fiber"})
                    excluded_ids.add(comp_food["food_id"])
            return components

        exclude_snacks = self.user.get("exclude_snacks", False)
        b_food = self.food_by_id[sol["breakfast"]]
        l_food = self.food_by_id[sol["lunch"]]
        s_food = None if exclude_snacks else self.food_by_id.get(sol.get("snack"))
        d_food = self.food_by_id[sol["dinner"]]

        is_rich_db = len(all_carbs) >= 1 and len(all_proteins) >= 1 and len(all_fibers) >= 1
        components = []
        if is_rich_db:
            comp_proteins_pool = all_proteins
            excluded_ids = set()
            components.append({"slot": "breakfast", "food": b_food, "role": "core"})
            if not exclude_snacks and s_food:
                components.append({"slot": "snack", "food": s_food, "role": "snack"})
            lunch_components = build_meal_components(l_food, "lunch", excluded_ids)
            components.extend(lunch_components)
            dinner_components = build_meal_components(d_food, "dinner", excluded_ids)
            components.extend(dinner_components)
        else:
            components = [{"slot": "breakfast", "food": b_food, "role": "core"}, {"slot": "lunch", "food": l_food, "role": "core"}]
            if not exclude_snacks and s_food:
                components.append({"slot": "snack", "food": s_food, "role": "snack"})
            components.append({"slot": "dinner", "food": d_food, "role": "core"})

        p_ratio = constraints.macro_ratios.get("protein", 0.3)
        c_ratio = constraints.macro_ratios.get("carbs", 0.4)
        f_ratio = constraints.macro_ratios.get("fat", 0.3)

        w_prot_space = [50.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0, 300.0]
        w_crb_space = [50.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0, 300.0]
        w_fix_space = [30.0, 50.0, 80.0, 100.0, 150.0]

        best_w_protein = 150.0
        best_w_carb = 150.0
        best_w_fixed = 100.0
        min_error = float("inf")

        for w_prot in w_prot_space:
            for w_crb in w_crb_space:
                for w_fix in w_fix_space:
                    skip_combo = False
                    total_cal = 0.0
                    total_p = 0.0
                    total_f = 0.0
                    total_c = 0.0
                    meal_cals = {"breakfast": 0.0, "lunch": 0.0, "dinner": 0.0, "snack": 0.0}
                    
                    for comp in components:
                        f = comp["food"]
                        slot = comp["slot"]
                        if slot == "snack":
                            w = w_fix
                        else:
                            is_p, is_c, is_f = get_food_role(f)
                            if is_standalone_main_dish(f):
                                w = w_prot
                            elif is_c:
                                w = w_crb
                            elif is_p:
                                w = w_prot
                            else:
                                w = w_fix
                        max_w = f.get("max_serving_g") or get_max_serving_g(f, self.is_gym)
                        if w > max_w:
                            skip_combo = True
                            break
                        item_cal = float(f.get("calories") or f.get("energy_kcal") or 0.0) * (w / 100.0)
                        total_cal += item_cal
                        meal_cals[slot] += item_cal
                        total_p += float(f.get("protein") or f.get("protein_g") or 0.0) * (w / 100.0)
                        total_f += float(f.get("fat") or f.get("fat_g") or 0.0) * (w / 100.0)
                        total_c += float(f.get("carbs") or f.get("carbs_g") or 0.0) * (w / 100.0)

                    if skip_combo:
                        continue

                    cal_error = abs(total_cal - constraints.daily_calorie_target) / constraints.daily_calorie_target
                    b_pct = meal_cals["breakfast"] / total_cal if total_cal > 0 else 0.0
                    l_pct = meal_cals["lunch"] / total_cal if total_cal > 0 else 0.0
                    d_pct = meal_cals["dinner"] / total_cal if total_cal > 0 else 0.0
                    dist_error = 0.0
                    if not (0.15 <= b_pct <= 0.35):
                        dist_error += abs(b_pct - 0.25)
                    if not (0.25 <= l_pct <= 0.45):
                        dist_error += abs(l_pct - 0.35)
                    if not (0.25 <= d_pct <= 0.45):
                        dist_error += abs(d_pct - 0.35)
                    cal_error += dist_error * 2.0

                    total_mass = total_p + total_f + total_c
                    if total_mass > 0:
                        macro_error = (
                            abs((total_p / total_mass) - p_ratio) +
                            abs((total_f / total_mass) - f_ratio) +
                            abs((total_c / total_mass) - c_ratio)
                        )
                    else:
                        macro_error = 1.0

                    error = cal_error + macro_error
                    
        if min_error == float("inf"):
            raise ValueError("No feasible portion size combination found")

        weights = {}
        for comp in components:
            f = comp["food"]
            slot = comp["slot"]
            if slot == "snack":
                w = best_w_fixed
            else:
                is_p, is_c, is_f = get_food_role(f)
                if is_standalone_main_dish(f):
                    w = best_w_protein
                elif is_c:
                    w = best_w_carb
                elif is_p:
                    w = best_w_protein
                else:
                    w = best_w_fixed
            weights[f["food_id"]] = w

        scaled_components = []
        for comp in components:
            f = comp["food"]
            w = weights[f["food_id"]]
            scaled = {
                **f,
                "weight_g": w,
                "calories": float(f.get("calories") or f.get("energy_kcal") or 0.0) * (w / 100.0),
                "protein": float(f.get("protein") or f.get("protein_g") or 0.0) * (w / 100.0),
                "fat": float(f.get("fat") or f.get("fat_g") or 0.0) * (w / 100.0),
                "carbs": float(f.get("carbs") or f.get("carbs_g") or 0.0) * (w / 100.0),
                "cost_vnd": float(f.get("cost_vnd_100g") or 15000) * (w / 100.0),
            }
            scaled_components.append({"slot": comp["slot"], "scaled_food": scaled})

        day_meals = []
        for slot in ["breakfast", "lunch", "snack", "dinner"] if not exclude_snacks else ["breakfast", "lunch", "dinner"]:
            slot_comps = [sc["scaled_food"] for sc in scaled_components if sc["slot"] == slot]
            if not slot_comps:
                continue
            combined_name = " + ".join([sc.get("name_vi") or "" for sc in slot_comps])
            day_meals.append({
                "meal_type": slot,
                "food_id": slot_comps[0]["food_id"],
                "name": combined_name,
                "calories": sum(sc["calories"] for sc in slot_comps),
                "protein": sum(sc["protein"] for sc in slot_comps),
                "fat": sum(sc["fat"] for sc in slot_comps),
                "carbs": sum(sc["carbs"] for sc in slot_comps),
                "cost_vnd_100g": sum(sc["cost_vnd"] for sc in slot_comps),
                "component_food_ids": [sc["food_id"] for sc in slot_comps],
            })
        return day_meals

user = {
    "daily_calorie_target": 1000,
    "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
    "allergies": ["duck", "vịt"],
    "budget_vnd_max": 100000,
}

scheduler = DiagnosticScheduler(user_profile=user, db_url="")

# Run exactly the day-by-day solver logic with prints for each day
constraints = NutrientConstraints(
    daily_calorie_target=1000.0,
    calorie_tolerance_pct=0.12,
    macro_ratios=user["macro_ratios"],
    macro_tolerance_pct=0.12,
    allergies=user["allergies"],
    budget_vnd_max=user["budget_vnd_max"],
    max_food_occurrences_per_week=2,
)

domain_foods = scheduler.foods
if constraints.allergies:
    domain_foods = [f for f in domain_foods if constraints.check_allergies([f])]

all_carbs = []
all_proteins = []
all_fibers = []
all_snacks = []
for f in scheduler.foods:
    role = classify_food(f)
    if role == "STAPLE_CARB":
        all_carbs.append(f)
    elif role == "MAIN_PROTEIN":
        all_proteins.append(f)
    elif role == "FIBER_SIDE":
        all_fibers.append(f)
    cat_clean = clean_category(f.get("category"))
    tags = f.get("tags") or set()
    if cat_clean == "trai_cay" or role == "ACCESSORY_CONDIMENT" or "is_dessert_snack" in tags:
        all_snacks.append(f)

if not all_carbs: all_carbs = [f for f in scheduler.foods if f["food_id"] in (3, 4)]
if not all_proteins: all_proteins = [f for f in scheduler.foods if f["food_id"] in (1, 2, 5, 6)]
if not all_fibers: all_fibers = [f for f in scheduler.foods if f["food_id"] == 9]
if not all_snacks: all_snacks = [f for f in scheduler.foods if f["food_id"] in (7, 8)]

def protein_priority(x):
    name = str(x.get("name_vi") or x.get("canonical_name_en") or "").lower()
    cat = str(x.get("category") or "").lower()
    tags = x.get("tags") or set()
    if any(k in name for k in ["khô", "sấy", "hộp", "canned", "bột", "powder"]):
        return 4
    if "sữa" in cat or "sua" in cat or "cheese" in cat or "phô mai" in name:
        return 3
    if "clean_protein" in tags:
        return 1
    return 2

def carb_priority(x):
    name = str(x.get("name_vi") or x.get("canonical_name_en") or "").lower()
    if any(k in name for k in ["sống", "raw", "bột", "tinh bột", "flour"]):
        return 3
    if "cơm" in name or "com" in name:
        return 1
    if any(k in name for k in ["bún", "bun", "phở", "pho", "bánh mì", "banh mi", "xôi", "xoi"]):
        return 2
    return 3

def fiber_priority(x):
    name = str(x.get("name_vi") or x.get("canonical_name_en") or "").lower()
    if any(k in name for k in ["khô", "sấy", "hộp", "canned", "mứt"]):
        return 3
    return 1

all_carbs.sort(key=lambda x: (carb_priority(x), int(x.get("source_priority") or 1)))
all_proteins.sort(key=lambda x: (protein_priority(x), int(x.get("source_priority") or 1)))
all_fibers.sort(key=lambda x: (fiber_priority(x), int(x.get("source_priority") or 1)))
all_snacks.sort(key=lambda x: int(x.get("source_priority") or 1))

exclude_snacks = False
used_food_ids = []
offal_blood_count = 0

from collections import Counter
from constraint import Problem

tolerance_multiplier = 1.0
print(f"Running 7 days solve simulation (multiplier={tolerance_multiplier})")

for day in range(7):
    print(f"\n--- DAY {day+1} ---")
    global_counts = Counter(used_food_ids)
    
    breakfast_foods = []
    lunch_foods = []
    snack_foods = []
    dinner_foods = []
    
    day_domain = domain_foods
    if offal_blood_count >= 1:
        day_domain = [f for f in day_domain if not is_offal_or_blood(f)]
        
    for f in day_domain:
        fid = int(f["food_id"])
        tags = f.get("tags") or set()
        cat_clean = clean_category(f.get("category"))
        is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
        
        name = str(f.get("name_vi") or f.get("canonical_name_en") or "").lower()
        is_com = ("cơm" in name or "com" in name) and ("mận" not in name)
        
        if not is_com:
            if global_counts[fid] >= 3:
                continue
        
        role = classify_food(f)
        if role == "ACCESSORY_CONDIMENT":
            if not exclude_snacks and (is_snack or cat_clean == "trai_cay"):
                snack_foods.append(fid)
            continue
        
        from csp.classification import get_max_serving_g
        max_serv = f.get("max_serving_g") or get_max_serving_g(f, scheduler.is_gym)
        cal_density = float(f.get("calories") or f.get("energy_kcal") or 0.0)
        max_cals = cal_density * (max_serv / 100.0)
        min_required_cals = float(user["daily_calorie_target"]) * 0.08
        is_valid_breakfast_cal = (max_cals >= min_required_cals)

        if "is_main_dish" in tags or is_single_bowl_meal(f):
            if not is_snack:
                if is_valid_breakfast_cal:
                    breakfast_foods.append(fid)
                lunch_foods.append(fid)
                dinner_foods.append(fid)
        else:
            if not is_snack:
                if is_valid_breakfast_cal:
                    if "allergen_egg" in tags or role == "STAPLE_CARB" or "allergen_milk" in tags:
                        breakfast_foods.append(fid)
                if role == "MAIN_PROTEIN" or role == "STAPLE_CARB" or role == "FIBER_SIDE":
                    lunch_foods.append(fid)
                    dinner_foods.append(fid)
            if is_snack or role == "FIBER_SIDE" or "allergen_milk" in tags or "allergen_peanut" in tags or cat_clean in ("trai_cay", "sua_che_pham", "hat", "khac", "rau_cu"):
                snack_foods.append(fid)

    print(f"Domain sizes: breakfast={len(breakfast_foods)}, lunch={len(lunch_foods)}, dinner={len(dinner_foods)}, snack={len(snack_foods)}")
    
    breakfast_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    lunch_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    dinner_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
    snack_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))

    # Capping & shuffling
    rng = random.Random(42 + day)
    MAX_C = 40
    breakfast_foods = list(breakfast_foods)[:MAX_C]
    lunch_foods = list(lunch_foods)[:MAX_C]
    dinner_foods = list(dinner_foods)[:MAX_C]
    snack_foods = list(snack_foods)[:MAX_C]
    
    rng.shuffle(breakfast_foods)
    rng.shuffle(lunch_foods)
    rng.shuffle(dinner_foods)
    rng.shuffle(snack_foods)

    day_carbs = list(all_carbs)
    day_proteins = list(all_proteins)
    day_fibers = list(all_fibers)
    day_snacks = list(all_snacks)
    
    rng.shuffle(day_carbs)
    rng.shuffle(day_proteins)
    rng.shuffle(day_fibers)
    rng.shuffle(day_snacks)
    
    day_carbs.sort(key=carb_priority)
    day_proteins.sort(key=protein_priority)
    day_fibers.sort(key=fiber_priority)

    prob = Problem()
    prob.addVariable("breakfast", breakfast_foods)
    prob.addVariable("lunch", lunch_foods)
    prob.addVariable("snack", snack_foods)
    prob.addVariable("dinner", dinner_foods)

    def check_daily_plan(b, l, s, d):
        return constraints.check_allergies([scheduler.food_by_id[b], scheduler.food_by_id[l], scheduler.food_by_id[s], scheduler.food_by_id[d]])
    prob.addConstraint(check_daily_plan, ["breakfast", "lunch", "snack", "dinner"])

    sols = prob.getSolutionIter()
    valid_scored = []
    checked_count = 0
    MAX_CHECKED = 150

    for sol in sols:
        if checked_count >= MAX_CHECKED:
            break
        checked_count += 1
        try:
            day_meals = scheduler._get_meal_plan_for_solution(
                sol, constraints, tolerance_multiplier,
                day_carbs, day_proteins, day_fibers, day_snacks,
                day_excluded_ids=set(used_food_ids)
            )
            
            cal_ok = constraints.check_daily_calories(day_meals, tolerance_multiplier)
            macro_ok = constraints.check_daily_macros(day_meals, tolerance_multiplier)
            costs = [m["cost_vnd_100g"] for m in day_meals]
            budget_ok = constraints.check_daily_budget(costs, tolerance_multiplier)
            dist_ok = constraints.check_calorie_distribution(day_meals, tolerance_multiplier)
            
            if cal_ok and macro_ok and budget_ok and dist_ok:
                from csp.objective import score_meal_plan
                score = score_meal_plan([{"meals": day_meals}], False, None)
                valid_scored.append((score, sol, day_meals))
        except Exception as e:
            if checked_count == 1:
                print("Exception on first solution:", str(e))
                import traceback
                traceback.print_exc()
            continue

    if not valid_scored:
        print(f"Failed to find solutions WITH day_excluded_ids. Trying without...")
        sols = prob.getSolutionIter()
        checked_count = 0
        for sol in sols:
            if checked_count >= MAX_CHECKED:
                break
            checked_count += 1
            try:
                day_meals = scheduler._get_meal_plan_for_solution(
                    sol, constraints, tolerance_multiplier,
                    day_carbs, day_proteins, day_fibers, day_snacks,
                    day_excluded_ids=None
                )
                cal_ok = constraints.check_daily_calories(day_meals, tolerance_multiplier)
                macro_ok = constraints.check_daily_macros(day_meals, tolerance_multiplier)
                costs = [m["cost_vnd_100g"] for m in day_meals]
                budget_ok = constraints.check_daily_budget(costs, tolerance_multiplier)
                dist_ok = constraints.check_calorie_distribution(day_meals, tolerance_multiplier)
                
                if cal_ok and macro_ok and budget_ok and dist_ok:
                    from csp.objective import score_meal_plan
                    score = score_meal_plan([{"meals": day_meals}], False, None)
                    valid_scored.append((score, sol, day_meals))
            except Exception:
                continue

    if not valid_scored:
        print(f"FAILED on day {day+1}!")
        failures = {"cal": 0, "macro": 0, "budget": 0, "dist": 0, "exception": 0}
        sols = prob.getSolutionIter()
        checked = 0
        for sol in sols:
            if checked >= 500:
                break
            checked += 1
            try:
                day_meals = scheduler._get_meal_plan_for_solution(
                    sol, constraints, tolerance_multiplier,
                    day_carbs, day_proteins, day_fibers, day_snacks,
                    day_excluded_ids=None
                )
                cal_ok = constraints.check_daily_calories(day_meals, tolerance_multiplier)
                macro_ok = constraints.check_daily_macros(day_meals, tolerance_multiplier)
                costs = [m["cost_vnd_100g"] for m in day_meals]
                budget_ok = constraints.check_daily_budget(costs, tolerance_multiplier)
                dist_ok = constraints.check_calorie_distribution(day_meals, tolerance_multiplier)
                
                if not cal_ok: failures["cal"] += 1
                if not macro_ok: failures["macro"] += 1
                if not budget_ok: failures["budget"] += 1
                if not dist_ok: failures["dist"] += 1
                
                if checked <= 5:
                    print(f"Candidate {checked}: calories={[m['calories'] for m in day_meals]}, types={[m['meal_type'] for m in day_meals]}")
                    print(f"  Breakfast food: {day_meals[0]['name']} (ID={day_meals[0]['food_id']}, Cal100g={scheduler.food_by_id[day_meals[0]['food_id']]['calories']})")
                    meal_cals = {"breakfast": 0.0, "lunch": 0.0, "dinner": 0.0}
                    total_c = 0.0
                    for m in day_meals:
                        cals = m["calories"]
                        total_c += cals
                        if m["meal_type"] in meal_cals:
                            meal_cals[m["meal_type"]] += cals
                    print(f"  Total actual cals: {total_c}")
                    print(f"  Pct: B={meal_cals['breakfast']/total_c:.2f}, L={meal_cals['lunch']/total_c:.2f}, D={meal_cals['dinner']/total_c:.2f}")
            except Exception as e:
                failures["exception"] += 1
        print("Detailed failures on Day", day+1, ":", failures)
        sys.exit(1)
    
    valid_scored.sort(key=lambda x: x[0], reverse=True)
    best_sol = valid_scored[0]
    print(f"SUCCESS on day {day+1}!")
    print(f"Selected: {best_sol[1]}")
    cand_ids = []
    for m in best_sol[2]:
        cand_ids.extend(m.get("component_food_ids", [m["food_id"]]))
    used_food_ids.extend(cand_ids)
    for fid in cand_ids:
        if is_offal_or_blood(scheduler.food_by_id[fid]):
            offal_blood_count += 1

print("\nALL 7 DAYS SOLVED SUCCESSFULLY!")
