import os
import sys
import dotenv
import time

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

# Pre-partition foods
all_carbs = []
all_proteins = []
all_fibers = []
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
    daily_calorie_target=2200.0,
    calorie_tolerance_pct=0.10,
    macro_ratios=user_profile["macro_ratios"],
    macro_tolerance_pct=0.10,
    allergies=user_profile["allergies"],
    budget_vnd_max=user_profile["budget_vnd_max"],
)

domain_foods_all = [f for f in scheduler.foods if constraints.check_allergies([f])]
print(f"Total eligible foods: {len(domain_foods_all)}")

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

print(f"breakfast_foods size: {len(breakfast_foods)}")
print(f"lunch_foods size: {len(lunch_foods)}")
print(f"dinner_foods size: {len(dinner_foods)}")

MAX_C = 150
breakfast_foods = breakfast_foods[:MAX_C]
lunch_foods = lunch_foods[:MAX_C]
dinner_foods = dinner_foods[:MAX_C]

from constraint import Problem
prob = Problem()
prob.addVariable("breakfast", breakfast_foods)
prob.addVariable("lunch", lunch_foods)
prob.addVariable("dinner", dinner_foods)

def check_daily_plan_3meals(b, l, d):
    b_food = scheduler.food_by_id[b]
    l_food = scheduler.food_by_id[l]
    d_food = scheduler.food_by_id[d]
    return constraints.check_allergies([b_food, l_food, d_food])
    
prob.addConstraint(check_daily_plan_3meals, ["breakfast", "lunch", "dinner"])

start_time = time.time()
print("Getting solution iterator...")
sols = prob.getSolutionIter()
print(f"Iterator obtained in {time.time() - start_time:.4f}s")

# Let's see how fast we can get the first few solutions
start_time = time.time()
sol_list = []
for i in range(100):
    try:
        sol = next(sols)
        sol_list.append(sol)
    except StopIteration:
        print("StopIteration reached")
        break
print(f"Obtained {len(sol_list)} solutions in {time.time() - start_time:.4f}s")
