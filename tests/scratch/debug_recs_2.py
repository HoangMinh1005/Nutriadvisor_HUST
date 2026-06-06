import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from backend.app.services.meal_plan_pipeline import MealPlanPipeline

def main():
    pipeline = MealPlanPipeline()
    pipeline.initialize()
    user_profile = {
        "daily_calorie_target": 2000,
        "macro_ratios": {"protein": 0.30, "fat": 0.30, "carbs": 0.40},
        "budget_vnd_max": 300000,
        "exclude_snacks": True,
        "allergies": [],
        "goal": "gym",
    }
    c_ids = pipeline.knn.recommend_for_profile(user_profile, n=400)
    print("Total recommended ids:", len(c_ids))
    print("Is 585 (Thịt bò loại I) in candidates?", 585 in c_ids)
    
    # Print what foods with 'bò' or 'cá' or 'hồi' are in candidates
    foods = pipeline.feature_store.get_food_details(c_ids)
    bò_foods = [f for f in foods if "bò" in str(f.get("name_vi")).lower()]
    cá_foods = [f for f in foods if "cá" in str(f.get("name_vi")).lower()]
    
    print(f"Bò foods in candidates ({len(bò_foods)}):")
    for f in bò_foods[:10]:
        print(f"  {f['food_id']}: {f['name_vi']} | cost_100g: {f.get('cost_vnd_100g')} | tags: {f.get('tags')}")
        
    print(f"Cá foods in candidates ({len(cá_foods)}):")
    for f in cá_foods[:10]:
        print(f"  {f['food_id']}: {f['name_vi']} | cost_100g: {f.get('cost_vnd_100g')} | tags: {f.get('tags')}")

if __name__ == "__main__":
    main()
