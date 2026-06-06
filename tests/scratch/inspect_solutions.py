import os
import sys
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, ".")

from csp import MealScheduler, NutrientConstraints
from csp.scheduler import get_dynamic_tags

user_profile = {
    "daily_calorie_target": 2200,
    "macro_ratios": {"protein": 0.30, "fat": 0.30, "carbs": 0.40},
    "budget_vnd_max": 200000,
    "exclude_snacks": True,
    "allergies": ["seafood", "hải sản"],
}

scheduler = MealScheduler(user_profile=user_profile)

# Let's run the _solve prep code manually to see what's in solutions_scored
from constraint import Problem
prob = Problem()

constraints = NutrientConstraints(
    daily_calorie_target=2200.0,
    calorie_tolerance_pct=0.10,
    macro_ratios=user_profile["macro_ratios"],
    macro_tolerance_pct=0.10,
    allergies=user_profile["allergies"],
    budget_vnd_max=user_profile["budget_vnd_max"],
)

domain_foods = scheduler.foods
# Apply the filters
if constraints.allergies:
    domain_foods = [f for f in domain_foods if constraints.check_allergies([f])]

MAX_DOMAIN_SIZE = 350
if len(domain_foods) > MAX_DOMAIN_SIZE:
    by_category = {}
    for f in domain_foods:
        cat = str(f.get("category") or "other").lower()
        by_category.setdefault(cat, []).append(f)
    
    selected = []
    category_lists = []
    for cat_list in by_category.values():
        cat_list.sort(key=lambda x: int(x.get("source_priority") or 1))
        category_lists.append(cat_list)
    
    if category_lists:
        idx = 0
        while len(selected) < MAX_DOMAIN_SIZE:
            added_any = False
            for cat_list in category_lists:
                if idx < len(cat_list):
                    selected.append(cat_list[idx])
                    added_any = True
                    if len(selected) >= MAX_DOMAIN_SIZE:
                        break
            if not added_any:
                break
            idx += 1
        domain_foods = selected

# Partition self.foods
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

breakfast_foods = []
lunch_foods = []
dinner_foods = []

from csp.scheduler import clean_category
for f in domain_foods:
    fid = int(f["food_id"])
    tags = f.get("tags") or set()
    cat_clean = clean_category(f.get("category"))
    is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
    
    if "is_main_dish" in tags:
        if not is_snack:
            breakfast_foods.append(fid)
            lunch_foods.append(fid)
            dinner_foods.append(fid)
    else:
        if not is_snack:
            if "allergen_egg" in tags or "role_carb" in tags or "allergen_milk" in tags or "role_fiber" in tags:
                breakfast_foods.append(fid)
            if "role_protein" in tags or "role_carb" in tags or "role_fiber" in tags:
                lunch_foods.append(fid)
                dinner_foods.append(fid)

prob.addVariable("breakfast", breakfast_foods)
prob.addVariable("lunch", lunch_foods)
prob.addVariable("dinner", dinner_foods)

def check_daily_plan_3meals(b, l, d):
    b_food = scheduler.food_by_id[b]
    l_food = scheduler.food_by_id[l]
    d_food = scheduler.food_by_id[d]
    return constraints.check_allergies([b_food, l_food, d_food])

prob.addConstraint(check_daily_plan_3meals, ["breakfast", "lunch", "dinner"])

sols = list(prob.getSolutionIter())
print("Total raw constraint solutions:", len(sols))

valid_scored = []
for sol in sols[:1000]:
    try:
        day_meals = scheduler._get_meal_plan_for_solution(
            sol, constraints, 1.0,
            all_carbs, all_proteins, all_fibers, []
        )
        if not constraints.check_daily_calories(day_meals, 1.0):
            continue
        if not constraints.check_daily_macros(day_meals, 1.0):
            continue
        costs = [m["cost_vnd_100g"] for m in day_meals]
        if not constraints.check_daily_budget(costs, 1.0):
            continue
        valid_scored.append((sol, day_meals))
    except Exception as e:
        pass

print("Total valid scored solutions (at tolerance_multiplier=1.0):", len(valid_scored))
for idx, (sol, meals) in enumerate(valid_scored[:10]):
    print(f"\nSolution {idx+1}: {sol}")
    for m in meals:
        print(f"  {m['meal_type']}: {m['name']} (Cal: {m['calories']:.1f}, Cost: {m['cost_vnd_100g']:.1f})")
