import os
import sys
import dotenv

dotenv.load_dotenv()
sys.path.insert(0, ".")

from csp import MealScheduler

scheduler = MealScheduler(user_profile={"daily_calorie_target": 2200})
print("Total foods loaded:", len(scheduler.foods))

# Count tags
from collections import Counter
tags_counter = Counter()
for f in scheduler.foods:
    tags_counter.update(f.get("tags", []))
print("Tag counts:")
for tag, count in tags_counter.most_common():
    print(f"  {tag}: {count}")

# Print sample proteins
print("\nSample clean proteins:")
clean_proteins = [f for f in scheduler.foods if "clean_protein" in f.get("tags", [])]
for f in clean_proteins[:20]:
    print(f"  ID: {f['food_id']} | Key: {f['canonical_key']} | Name_vi: {f['name_vi']} | Name_en: {f['canonical_name_en']} | Category: {f['category']}")

# Print sample carbs
print("\nSample role_carb:")
role_carbs = [f for f in scheduler.foods if "role_carb" in f.get("tags", [])]
for f in role_carbs[:20]:
    print(f"  ID: {f['food_id']} | Key: {f['canonical_key']} | Name_vi: {f['name_vi']} | Name_en: {f['canonical_name_en']} | Category: {f['category']}")
