import sys, csv
sys.path.insert(0, ".")
from csp.constraints import NutrientConstraints

allergens = ["hải sản", "seafood", "tôm", "cua", "cá", "fish", "shrimp", "crab", "salmon", "tuna"]
c = NutrientConstraints(allergies=allergens)

foods = list(csv.DictReader(open("data/raw/final_nutrients_structured.csv", "r", encoding="utf-8")))
total = len(foods)

# Check how many foods get filtered out  
filtered_out = []
kept = []
for f in foods:
    food_dict = {
        "canonical_name_en": f.get("canonical_name_en", ""),
        "name_vi": f.get("name_vi", ""),
        "category": f.get("category", ""),
    }
    if c.check_allergies([food_dict]):
        kept.append(food_dict)
    else:
        filtered_out.append(food_dict)

print(f"Total foods: {total}")
print(f"Kept: {len(kept)}")  
print(f"Filtered out: {len(filtered_out)}")
print(f"\nSample filtered out (first 20):")
for f in filtered_out[:20]:
    print(f"  - {f['name_vi']} | {f['category']} | {f['canonical_name_en']}")

# Check specifically: does "cá" match "các" ?
print(f"\n--- Substring test ---")
print(f"'cá' in 'các món khác' = {'cá' in 'các món khác'}")
print(f"'cá' in 'các loại bánh' = {'cá' in 'các loại bánh'}")
print(f"'cá' in 'cá hồi'       = {'cá' in 'cá hồi'}")

# Count by category
from collections import Counter
cat_counts = Counter(f["category"] for f in filtered_out)
print(f"\nFiltered out by category:")
for cat, count in cat_counts.most_common(15):
    print(f"  {cat}: {count} foods removed")
