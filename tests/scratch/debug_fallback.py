import sys
sys.path.insert(0, ".")

from csp import MealScheduler, NutrientConstraints
from csp.classification import classify_food, get_dynamic_tags, clean_category
import random

user = {
    "daily_calorie_target": 1000,
    "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
    "allergies": ["duck", "vịt"],
    "budget_vnd_max": 100000,
}

scheduler = MealScheduler(user_profile=user, db_url="")
constraints = NutrientConstraints(
    daily_calorie_target=1000.0,
    calorie_tolerance_pct=0.12,
    macro_ratios=user["macro_ratios"],
    macro_tolerance_pct=0.12,
    allergies=user["allergies"],
    budget_vnd_max=user["budget_vnd_max"],
    max_food_occurrences_per_week=2,
)

# Run solver's logic but dump constraints failures
print("Starting manual solve tracing for day 1...")
# Gather all domains
all_carbs = []
all_proteins = []
all_fibers = []
all_snacks = []

filtered_foods = scheduler.foods
for f in filtered_foods:
    tags = f.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(f)
        f["tags"] = tags
        
    role = classify_food(f)
    if role == "STAPLE_CARB":
        all_carbs.append(f)
    elif role == "MAIN_PROTEIN":
        all_proteins.append(f)
    elif role == "FIBER_SIDE":
        all_fibers.append(f)
        
    cat_clean = clean_category(f.get("category"))
    if cat_clean == "trai_cay" or role == "ACCESSORY_CONDIMENT" or "is_dessert_snack" in tags:
        all_snacks.append(f)

# Fallback lists if empty
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

# Build domains for Day 1
day_domain = [f for f in scheduler.foods if constraints.check_allergies([f])]

breakfast_foods = []
lunch_foods = []
snack_foods = []
dinner_foods = []

for f in day_domain:
    fid = int(f["food_id"])
    tags = f.get("tags") or set()
    cat_clean = clean_category(f.get("category"))
    is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
    
    role = classify_food(f)
    if role == "ACCESSORY_CONDIMENT":
        if is_snack or cat_clean == "trai_cay":
            snack_foods.append(fid)
        continue
    
    if "is_main_dish" in tags or scheduler.foods[fid-1].get("is_main_dish") or is_snack: # Wait, logic in scheduler:
        # standard scheduler filter:
        pass

# Let's run a test loop with tolerance_multiplier = 1.0, 1.25, 1.5, 1.75
# Let's trace it directly inside scheduler code by invoking custom trace method
# We will do this by injecting print statements to scheduler's check code or running manually.
# Let's see what happens if we inspect the check functions.
# Let's write a script that runs check_daily_calories, check_daily_macros, check_calorie_distribution on a generated meal plan.

# Let's run the actual solver's _solve step but log the failures of the first 100 solutions:
from constraint import Problem

# day 0 lists:
breakfast_foods = []
lunch_foods = []
snack_foods = []
dinner_foods = []

for f in day_domain:
    fid = int(f["food_id"])
    tags = f.get("tags") or set()
    cat_clean = clean_category(f.get("category"))
    is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
    
    role = classify_food(f)
    if role == "ACCESSORY_CONDIMENT":
        if is_snack or cat_clean == "trai_cay":
            snack_foods.append(fid)
        continue
    
    is_single_bowl = (role in ("MAIN_PROTEIN", "STAPLE_CARB") and "is_main_dish" in tags)
    if "is_main_dish" in tags or is_single_bowl:
        if not is_snack:
            breakfast_foods.append(fid)
            lunch_foods.append(fid)
            dinner_foods.append(fid)
    else:
        if not is_snack:
            if "allergen_egg" in tags or role == "STAPLE_CARB" or "allergen_milk" in tags or role == "FIBER_SIDE":
                breakfast_foods.append(fid)
            if role == "MAIN_PROTEIN" or role == "STAPLE_CARB" or role == "FIBER_SIDE":
                lunch_foods.append(fid)
                dinner_foods.append(fid)
        if is_snack or role == "FIBER_SIDE" or "allergen_milk" in tags or "allergen_peanut" in tags or cat_clean in ("trai_cay", "sua_che_pham", "hat", "khac", "rau_cu"):
            snack_foods.append(fid)

# Prios
breakfast_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
lunch_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
dinner_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))
snack_foods.sort(key=lambda x: int(scheduler.food_by_id[x].get("source_priority") or 1))

breakfast_foods = list(breakfast_foods)[:40]
lunch_foods = list(lunch_foods)[:40]
dinner_foods = list(dinner_foods)[:40]
snack_foods = list(snack_foods)[:40]

prob = Problem()
prob.addVariable("breakfast", breakfast_foods)
prob.addVariable("lunch", lunch_foods)
prob.addVariable("snack", snack_foods)
prob.addVariable("dinner", dinner_foods)

def check_daily_plan(b, l, s, d):
    return constraints.check_allergies([scheduler.food_by_id[b], scheduler.food_by_id[l], scheduler.food_by_id[s], scheduler.food_by_id[d]])
prob.addConstraint(check_daily_plan, ["breakfast", "lunch", "snack", "dinner"])

sols = prob.getSolutionIter()

failures = {
    "cal": 0,
    "macro": 0,
    "budget": 0,
    "dist": 0,
    "exception": 0,
}

checked_count = 0
for sol in sols:
    if checked_count >= 1000:
        break
    checked_count += 1
    try:
        day_meals = scheduler._get_meal_plan_for_solution(
            sol, constraints, 1.0,
            all_carbs, all_proteins, all_fibers, all_snacks
        )
        
        cal_ok = constraints.check_daily_calories(day_meals, 1.0)
        macro_ok = constraints.check_daily_macros(day_meals, 1.0)
        costs = [m["cost_vnd_100g"] for m in day_meals]
        budget_ok = constraints.check_daily_budget(costs, 1.0)
        dist_ok = constraints.check_calorie_distribution(day_meals, 1.0)
        
        if not cal_ok:
            failures["cal"] += 1
        if not macro_ok:
            failures["macro"] += 1
        if not budget_ok:
            failures["budget"] += 1
        if not dist_ok:
            failures["dist"] += 1
            
        if cal_ok and macro_ok and budget_ok and dist_ok:
            print("FOUND FEASIBLE MEAL PLAN!", sol)
            for m in day_meals:
                print(f"  {m['meal_type']}: {m['name']} (Cal={m['calories']}, Prot={m['protein']}, Fat={m['fat']}, Carb={m['carbs']}, Cost={m['cost_vnd_100g']})")
            sys.exit(0)
            
    except Exception as e:
        failures["exception"] += 1

print("Failures summary:")
print(failures)
