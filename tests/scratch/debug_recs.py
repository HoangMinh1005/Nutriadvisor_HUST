import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from backend.app.services.meal_plan_pipeline import MealPlanPipeline
from csp.scheduler import MealScheduler

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

    print("Total foods:", len(sched.foods))
    print("704 details:", sched.food_by_id.get(704))
    
    from csp.classification import classify_food
    # Classify all foods
    all_proteins = []
    for f in sched.foods:
        role = classify_food(f)
        if role == "MAIN_PROTEIN":
            all_proteins.append(f)
            
    print("Total proteins:", len(all_proteins))
    
    lunch_foods = [f["food_id"] for f in all_proteins]
    lunch_candidates = list(set(lunch_foods))
    
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
    print("Top 15 lunch candidates:")
    for fid in lunch_candidates[:15]:
        food = sched.food_by_id[fid]
        print(f"  ID {fid}: {food['name_vi']} | Gym Priority Score: {sort_by_gym_priority(fid)} | Tags: {food.get('tags')}")

if __name__ == "__main__":
    main()
