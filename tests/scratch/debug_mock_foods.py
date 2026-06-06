import sys
sys.path.insert(0, ".")

from csp import MealScheduler
from csp.scheduler import classify_food, get_dynamic_tags

rich_mock_foods = [
    {"food_id": 1, "canonical_name_en": "Chicken Breast", "name_vi": "ức gà", "calories": 165, "protein": 31, "fat": 3.6, "carbs": 0, "cost_vnd_100g": 15000, "category": "thịt_gia_cầm"},
    {"food_id": 2, "canonical_name_en": "Egg", "name_vi": "trứng", "calories": 155, "protein": 13, "fat": 11, "carbs": 1.1, "cost_vnd_100g": 4000, "category": "trứng"},
    {"food_id": 3, "canonical_name_en": "Oats", "name_vi": "yến mạch", "calories": 389, "protein": 16.9, "fat": 6.9, "carbs": 66.3, "cost_vnd_100g": 10000, "category": "tinh_bột"},
    {"food_id": 4, "canonical_name_en": "White Rice", "name_vi": "cơm trắng", "calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28, "cost_vnd_100g": 1800, "category": "tinh_bột"},
    {"food_id": 5, "canonical_name_en": "Beef", "name_vi": "thịt bò", "calories": 250, "protein": 26, "fat": 15, "carbs": 0, "cost_vnd_100g": 25000, "category": "thịt_đỏ"},
    {"food_id": 6, "canonical_name_en": "Salmon", "name_vi": "cá hồi", "calories": 208, "protein": 20, "fat": 13, "carbs": 0, "cost_vnd_100g": 45000, "category": "cá_hải_sản"},
    {"food_id": 7, "canonical_name_en": "Milk", "name_vi": "sữa tươi", "calories": 60, "protein": 3.2, "fat": 3.25, "carbs": 4.8, "cost_vnd_100g": 3000, "category": "sữa"},
    {"food_id": 8, "canonical_name_en": "Banana", "name_vi": "chuối", "calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 22.8, "cost_vnd_100g": 2000, "category": "trái_cây"},
    {"food_id": 9, "canonical_name_en": "Cabbage", "name_vi": "rau cải", "calories": 25, "protein": 1.3, "fat": 0.1, "carbs": 5.8, "cost_vnd_100g": 1500, "category": "rau_xanh"},
    {"food_id": 10, "canonical_name_en": "Duck", "name_vi": "thịt vịt", "calories": 337, "protein": 19, "fat": 28, "carbs": 0, "cost_vnd_100g": 18000, "category": "thịt_gia_cầm"},
    {"food_id": 11, "canonical_name_en": "Bread", "name_vi": "bánh mì", "calories": 265, "protein": 9, "fat": 3.2, "carbs": 49, "cost_vnd_100g": 5000, "category": "tinh_bột"},
    {"food_id": 12, "canonical_name_en": "Sweet Potato", "name_vi": "khoai lang", "calories": 86, "protein": 1.6, "fat": 0.1, "carbs": 20, "cost_vnd_100g": 3000, "category": "tinh_bột"},
    {"food_id": 13, "canonical_name_en": "Pork", "name_vi": "thịt heo", "calories": 242, "protein": 27, "fat": 14, "carbs": 0, "cost_vnd_100g": 14000, "category": "thịt_lợn"},
    {"food_id": 14, "canonical_name_en": "Spinach", "name_vi": "rau bó xôi", "calories": 23, "protein": 2.9, "fat": 0.4, "carbs": 3.6, "cost_vnd_100g": 4000, "category": "rau_xanh"},
    {"food_id": 15, "canonical_name_en": "Broccoli", "name_vi": "súp lơ xanh", "calories": 34, "protein": 2.8, "fat": 0.4, "carbs": 7, "cost_vnd_100g": 5000, "category": "rau_xanh"},
    {"food_id": 16, "canonical_name_en": "Brown Rice", "name_vi": "cơm lứt", "calories": 111, "protein": 2.6, "fat": 0.9, "carbs": 23, "cost_vnd_100g": 3000, "category": "tinh_bột"},
    {"food_id": 17, "canonical_name_en": "Beef Pho", "name_vi": "Phở bò chín bình dân", "calories": 350, "protein": 15, "fat": 8, "carbs": 45, "cost_vnd_100g": 10000, "category": "món_chính"},
    {"food_id": 18, "canonical_name_en": "Stir-fried Noodles", "name_vi": "Mỳ xào thập cẩm", "calories": 400, "protein": 12, "fat": 15, "carbs": 50, "cost_vnd_100g": 12000, "category": "món_chính"},
    {"food_id": 19, "canonical_name_en": "Dried Jackfruit", "name_vi": "Mít khô", "calories": 280, "protein": 2, "fat": 1, "carbs": 70, "cost_vnd_100g": 35000, "category": "đồ_ăn_vặt"},
    {"food_id": 20, "canonical_name_en": "Tuna", "name_vi": "cá ngừ tươi", "calories": 130, "protein": 28, "fat": 1.2, "carbs": 0, "cost_vnd_100g": 20000, "category": "cá_hải_sản"},
    {"food_id": 21, "canonical_name_en": "Shrimp", "name_vi": "tôm", "calories": 99, "protein": 24, "fat": 0.3, "carbs": 0.2, "cost_vnd_100g": 30000, "category": "cá_hải_sản"},
    {"food_id": 22, "canonical_name_en": "Morning Glory", "name_vi": "rau muống", "calories": 19, "protein": 2.6, "fat": 0.1, "carbs": 3.1, "cost_vnd_100g": 1000, "category": "rau_xanh"},
    {"food_id": 23, "canonical_name_en": "Nấm rơm", "name_vi": "nấm rơm", "calories": 35, "protein": 3.8, "fat": 0.5, "carbs": 4.0, "cost_vnd_100g": 8000, "category": "rau_xanh"},
]

user = {
    "daily_calorie_target": 1800,
    "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
    "budget_vnd_max": 250000,
}

print("Running mock foods check...")
for f in rich_mock_foods:
    tags = get_dynamic_tags(f)
    f["tags"] = tags
    role = classify_food(f)
    print(f"ID={f['food_id']} Name={f['name_vi']} Role={role} Tags={tags}")

scheduler = MealScheduler(user_profile=user, available_foods=rich_mock_foods, db_url="")
res = scheduler.solve_with_relaxation()
print("Feasible:", res["feasible"])
if not res["feasible"]:
    print("Solver failed. Trying debug logic.")
