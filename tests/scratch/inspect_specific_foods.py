import os
import sys
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, ".")

from csp import MealScheduler

scheduler = MealScheduler(user_profile={"daily_calorie_target": 2200})

for f in scheduler.foods:
    name_vi = str(f.get("name_vi") or "").lower()
    name_en = str(f.get("canonical_name_en") or "").lower()
    if "trứng chiên" in name_vi or "trứng chiên" in name_en or "fried egg" in name_en or "turkey, roast" in name_en or "gà tây" in name_vi or "turkey" in name_en or "egg" in name_en:
        if any(k in name_vi or k in name_en for k in ["trứng chiên", "gà tây", "turkey", "fried egg"]):
            print(f"ID: {f['food_id']} | Key: {f['canonical_key']} | Name_vi: {f['name_vi']} | Name_en: {f['canonical_name_en']} | source: {f.get('source_name')} | priority: {f.get('source_priority')} | category: {f['category']}")
