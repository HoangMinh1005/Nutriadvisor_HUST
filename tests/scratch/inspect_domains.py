import os
import sys
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, ".")

from csp import MealScheduler, NutrientConstraints
from csp.scheduler import get_dynamic_tags, clean_category

user_profile = {
    "daily_calorie_target": 2200,
    "macro_ratios": {"protein": 0.30, "fat": 0.30, "carbs": 0.40},
    "budget_vnd_max": 200000,
    "exclude_snacks": True,
    "allergies": ["seafood", "hải sản"],
}

scheduler = MealScheduler(user_profile=user_profile)

constraints = NutrientConstraints(
    daily_calorie_target=2200.0,
    calorie_tolerance_pct=0.10,
    macro_ratios=user_profile["macro_ratios"],
    macro_tolerance_pct=0.10,
    allergies=user_profile["allergies"],
    budget_vnd_max=user_profile["budget_vnd_max"],
)

domain_foods_all = [f for f in scheduler.foods if constraints.check_allergies([f])]

breakfast_foods = []
lunch_foods = []
dinner_foods = []

for f in domain_foods_all:
    fid = int(f["food_id"])
    tags = f.get("tags") or set()
    cat_clean = clean_category(f.get("category"))
    is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
    
    if is_snack:
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

def food_priority_key(fid):
    f = scheduler.food_by_id[fid]
    name = str(f.get("name_vi") or f.get("canonical_name_en") or "").lower()
    tags = f.get("tags") or set()
    
    is_com = "cơm" in name or "com" in name
    is_noodle = any(k in name for k in ["bún", "bun", "miến", "mien", "phở", "pho", "bánh mì", "banh mi", "xôi", "xoi"])
    is_main = "is_main_dish" in tags
    
    if is_com:
        rank = 1
    elif is_noodle:
        rank = 2
    elif is_main:
        rank = 3
    else:
        rank = 4
        
    source_priority = int(f.get("source_priority") or 1)
    return (rank, source_priority, fid)

breakfast_foods.sort(key=food_priority_key)
lunch_foods.sort(key=food_priority_key)
dinner_foods.sort(key=food_priority_key)

print("--- TOP 12 BREAKFAST FOODS ---")
for fid in breakfast_foods[:12]:
    f = scheduler.food_by_id[fid]
    print(f"ID {fid}: {f['name_vi']} (Cal: {f['calories']}, P: {f['protein']}, F: {f['fat']}, C: {f['carbs']}, Source priority: {f.get('source_priority')})")

print("\n--- TOP 18 LUNCH FOODS ---")
for fid in lunch_foods[:18]:
    f = scheduler.food_by_id[fid]
    print(f"ID {fid}: {f['name_vi']} (Cal: {f['calories']}, P: {f['protein']}, F: {f['fat']}, C: {f['carbs']}, Source priority: {f.get('source_priority')})")
