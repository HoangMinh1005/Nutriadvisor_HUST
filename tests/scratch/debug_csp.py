import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from backend.app.services.meal_plan_pipeline import MealPlanPipeline
from csp.scheduler import MealScheduler
from constraint import Problem

def main():
    pipeline = MealPlanPipeline()
    pipeline.initialize()
    user_profile = {
        "daily_calorie_target": 1800,
        "macro_ratios": {"protein": 0.30, "fat": 0.20, "carbs": 0.50},
        "budget_vnd_max": 200000,
        "exclude_snacks": True,
        "allergies": ["seafood", "hải sản"],
    }
    c_ids = pipeline.knn.recommend_for_profile(user_profile, n=400)
    sched = MealScheduler(
        user_profile=user_profile,
        available_foods=pipeline.feature_store.get_food_details(c_ids),
        db_url=pipeline.db_url,
        candidate_food_ids=c_ids,
    )

    # Let's run a manual day _solve but print details of solutions involving 704
    from csp.classification import classify_food, clean_category, is_offal_or_blood
    from csp.constraints import NutrientConstraints

    constraints = NutrientConstraints(
        daily_calorie_target=1800.0,
        calorie_tolerance_pct=0.12,
        macro_ratios=user_profile["macro_ratios"],
        macro_tolerance_pct=0.12,
        allergies=user_profile["allergies"],
        budget_vnd_max=user_profile["budget_vnd_max"],
        max_food_occurrences_per_week=3,
    )

    all_carbs, all_proteins, all_fibers, all_snacks = [], [], [], []
    for f in sched.foods:
        role = classify_food(f)
        tags = f.get("tags") or set()
        cat_clean = clean_category(f.get("category"))
        if role == "ACCESSORY_CONDIMENT":
            continue
        if role == "STAPLE_CARB": all_carbs.append(f)
        elif role == "MAIN_PROTEIN": all_proteins.append(f)
        elif role == "FIBER_SIDE": all_fibers.append(f)

    breakfast_foods, lunch_foods, dinner_foods, snack_foods = [], [], [], []
    for f in sched.foods:
        fid = int(f["food_id"])
        role = classify_food(f)
        name_vi = str(f.get("name_vi") or "").lower()
        
        is_valid_vietnamese_breakfast = any(k in name_vi for k in ["bún", "miến", "phở", "cháo", "xôi", "bánh mì", "bánh mỳ", "bánh cuốn"])
        is_snack_cake = any(k in name_vi for k in ["bánh nếp", "bánh trôi", "bánh chay", "bánh tẻ", "bánh gio", "bánh cốm", "bánh rán", "bánh đa nem", "bánh quẩy", "bánh mì, vuông, ngọt"])

        if is_valid_vietnamese_breakfast and not is_snack_cake:
            breakfast_foods.append(fid)
        if role == "MAIN_PROTEIN" and not is_snack_cake:
            lunch_foods.append(fid)
            dinner_foods.append(fid)

    breakfast_candidates = list(set(breakfast_foods))
    lunch_candidates = list(set(lunch_foods))
    dinner_candidates = list(set(dinner_foods))

    def sort_by_gym_priority(fid):
        food_item = sched.food_by_id[fid]
        tags = food_item.get("tags") or set()
        name_low = str(food_item.get("name_vi") or "").lower()
        if "clean_protein" in tags and any(k in name_low for k in ["ức gà", "lườn gà", "gà công nghiệp"]):
            return 0
        if "clean_protein" in tags:
            return 1
        return 2

    lunch_candidates.sort(key=sort_by_gym_priority)
    dinner_candidates.sort(key=sort_by_gym_priority)

    # Let's test a simple combination: breakfast = Xôi đỗ xanh, lunch = 704, dinner = 704
    # and see if sched._get_meal_plan_for_solution succeeds, or raises an error, or is rejected.
    test_sol = {
        "breakfast": next(fid for fid in breakfast_candidates if "xôi đỗ xanh" in sched.food_by_id[fid]["name_vi"].lower()),
        "lunch": 704,
        "dinner": 704
    }
    
    print("\nTesting test_sol:", {k: sched.food_by_id[v]["name_vi"] for k, v in test_sol.items()})
    
    # Let's inspect the weights logic manually
    components = []
    components.append({"slot": "breakfast", "food": sched.food_by_id[test_sol["breakfast"]], "role": "core"})
    
    rice_food = next((f for f in sched.foods if any(k in str(f.get("name_vi")).lower() for k in ["cơm tẻ", "cơm trắng", "cơm chín"])), None)
    for slot in ["lunch", "dinner"]:
        if rice_food:
            components.append({"slot": slot, "food": rice_food, "role": "carb"})
        components.append({"slot": slot, "food": sched.food_by_id[test_sol[slot]], "role": "protein"})
        # Let's add a dummy fiber for test
        comp_fiber = all_fibers[0]
        components.append({"slot": slot, "food": comp_fiber, "role": "fiber"})

    print("Components:")
    for c in components:
        print(f"  {c['slot']} - {c['role']}: {c['food']['name_vi']} (Max serving: {c['food'].get('max_serving_g')})")

    p_ratio = constraints.macro_ratios.get("protein", 0.4)
    c_ratio = constraints.macro_ratios.get("carbs", 0.3)
    f_ratio = constraints.macro_ratios.get("fat", 0.3)

    w_prot_space = [150.0, 180.0, 220.0, 260.0, 300.0, 350.0]
    w_crb_space = [100.0, 140.0, 180.0, 220.0, 260.0, 300.0]
    w_fix_space = [100.0, 120.0, 150.0]

    checked_count = 0
    valid_count = 0
    for w_prot in w_prot_space:
        for w_crb in w_crb_space:
            for w_fix in w_fix_space:
                skip_combo = False
                total_cal, total_p, total_f, total_c = 0.0, 0.0, 0.0, 0.0
                
                for comp in components:
                    f = comp["food"]
                    slot = comp["slot"]
                    role = comp.get("role", "core")
                    
                    if slot == "snack": w = w_fix
                    else:
                        if role == "carb" or "cơm" in str(f.get("name_vi")).lower(): w = w_crb
                        elif role in ["protein", "core"] and (classify_food(f) == "MAIN_PROTEIN"): w = w_prot
                        else: w = w_fix
                    
                    max_w = f.get("max_serving_g") or 450.0
                    if w > max_w:
                        skip_combo = True
                        break
                    
                    factor = w / 100.0
                    total_cal += float(f.get("calories") or 0.0) * factor
                    total_p += float(f.get("protein") or 0.0) * factor
                    total_f += float(f.get("fat") or 0.0) * factor
                    total_c += float(f.get("carbs") or 0.0) * factor
                    
                if skip_combo:
                    continue
                    
                checked_count += 1
                cal_error = abs(total_cal - constraints.daily_calorie_target) / constraints.daily_calorie_target
                
                # Check calorie tolerance (typically 0.12)
                if cal_error <= constraints.calorie_tolerance_pct:
                    # check macros
                    total_mass = total_p + total_f + total_c
                    if total_mass > 0:
                        protein_ratio = total_p / total_mass
                        fat_ratio = total_f / total_mass
                        carbs_ratio = total_c / total_mass
                        
                        max_single_dev = constraints.macro_tolerance_pct + 0.08
                        p_dev = abs(protein_ratio - p_ratio)
                        f_dev = abs(fat_ratio - f_ratio)
                        c_dev = abs(carbs_ratio - c_ratio)
                        
                        is_macro_ok = (p_dev <= max_single_dev and f_dev <= max_single_dev and c_dev <= max_single_dev)
                        total_dev = p_dev + f_dev + c_dev
                        is_total_dev_ok = (total_dev <= constraints.macro_tolerance_pct * 2.5)
                        
                        if is_macro_ok and is_total_dev_ok:
                            valid_count += 1
                            if valid_count <= 5:
                                print(f"Valid Combo {valid_count}: w_prot={w_prot}, w_crb={w_crb}, w_fix={w_fix} | Cal={total_cal:.1f} | P={protein_ratio*100:.1f}%, F={fat_ratio*100:.1f}%, C={carbs_ratio*100:.1f}%")
                            
    print(f"Checked combinations: {checked_count}, Valid combinations: {valid_count}")

if __name__ == "__main__":
    main()
