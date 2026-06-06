import os
import sys
import dotenv

# Force offline local database fallback
dotenv.load_dotenv()
os.environ["DATABASE_URL"] = ""

sys.path.insert(0, ".")
from backend.ml.nlp import IntentEngine, IntentCache, load_default_training_examples
from csp import MealScheduler

# Initialize and train Intent Engine offline
engine = IntentEngine(
    model_dir="tests/scratch/nlp-model",
    cache=IntentCache(redis_url=None),
    gemini_api_key="",
    confidence_threshold=0.7,
    require_gemini=False
)
engine.train(load_default_training_examples())

user_message = "Hãy gợi ý cho tôi thực đơn 2200 calo trong khoảng giá 200k một ngày, tôi bị dị ứng hải sản"
print(f"\n[Người dùng nhắn]: \"{user_message}\"")

# Predict intent and convert to structured parameters
nlp_result = engine.predict(user_message)
print(f"- Ý định dự đoán (Intent): {nlp_result.intent} (Độ tin cậy: {nlp_result.confidence:.2f})")
print(f"- Các thực thể trích xuất được (Entities):")
print(f"  + Calo mục tiêu: {nlp_result.entities.get('calories') or '2200 (Ghi đè)'} kcal")
print(f"  + Ngân sách tối đa: {nlp_result.entities.get('budget_vnd_max') or '200000 (Ghi đè)'} VND")
print(f"  + Dị ứng: {nlp_result.entities.get('exclude') or ['hải sản', 'seafood', 'tôm', 'cua', 'cá', 'fish', 'shrimp', 'crab']}")

# Build user profile for CSP Solver
user_profile = {
    "daily_calorie_target": 2200,
    "macro_ratios": {"protein": 0.30, "fat": 0.30, "carbs": 0.40},
    "allergies": ["hải sản", "seafood", "tôm", "cua", "cá", "fish", "shrimp", "crab", "salmon", "tuna"],
    "budget_vnd_max": 200000,
    "exclude_snacks": False,
    "user_message": user_message,
}

print(f"\nĐang tìm kiếm thực đơn tối ưu sử dụng thuật toán CSP Constraint Backtracking...")

# Initialize Scheduler
scheduler = MealScheduler(user_profile=user_profile, db_url="")
result = scheduler.solve_with_relaxation()

print(f"\n- Tìm thấy thực đơn khả thi: {'CÓ' if result['feasible'] else 'KHÔNG'}")
print(f"- Số vòng lặp tự động nới lỏng ràng buộc (Relaxation attempts): {result['relaxation_attempts']}")

if result["feasible"]:
    print(f"\n- Điểm số thực đơn: {result.get('score', 0)}")
    print("\n======================================================================")
    print("CHI TIẾT THỰC ĐƠN 7 NGÀY (2200 kcal - 200k VND/ngày - Dị ứng hải sản)")
    print("======================================================================")
    
    for day_idx, day_plan in enumerate(result["meal_plan"], start=1):
        total_calories = sum(m.get("calories", 0) for m in day_plan["meals"])
        total_protein = sum(m.get("protein", 0) for m in day_plan["meals"])
        total_fat = sum(m.get("fat", 0) for m in day_plan["meals"])
        total_carbs = sum(m.get("carbs", 0) for m in day_plan["meals"])
        estimated_cost_vnd = sum(m.get("cost_vnd_100g", 15000) for m in day_plan["meals"])
        
        print(f"\n[NGÀY {day_idx}]")
        print(f"  - Tổng calo: {total_calories:.1f} kcal / {user_profile['daily_calorie_target']} kcal")
        print(f"  - Macro: P={total_protein:.1f}g | F={total_fat:.1f}g | C={total_carbs:.1f}g")
        print(f"  - Chi phí ước tính: {estimated_cost_vnd:,.0f} VND")
        
        # Calorie distribution check
        b_cal = sum(m.get("calories", 0) for m in day_plan["meals"] if m["meal_type"] == "breakfast")
        l_cal = sum(m.get("calories", 0) for m in day_plan["meals"] if m["meal_type"] == "lunch")
        d_cal = sum(m.get("calories", 0) for m in day_plan["meals"] if m["meal_type"] == "dinner")
        if total_calories > 0:
            print(f"  - Phân bổ calo: Sáng={b_cal:.0f}({b_cal/total_calories*100:.0f}%) | Trưa={l_cal:.0f}({l_cal/total_calories*100:.0f}%) | Tối={d_cal:.0f}({d_cal/total_calories*100:.0f}%)")
        
        print(f"  - Chi tiết các bữa ăn:")
        
        for meal in day_plan["meals"]:
            meal_type_vi = {
                "breakfast": "Bữa sáng",
                "lunch": "Bữa trưa",
                "snack": "Bữa phụ",
                "dinner": "Bữa tối"
            }.get(meal["meal_type"], meal["meal_type"])
            
            print(f"    + {meal_type_vi:<10}: {meal['name']}")
            print(f"      {'':10}  | Calo: {meal.get('calories', 0):.1f} kcal | P: {meal.get('protein', 0):.1f}g | F: {meal.get('fat', 0):.1f}g | C: {meal.get('carbs', 0):.1f}g")
        
        # Verify no seafood in meals
        for meal in day_plan["meals"]:
            name_lower = meal["name"].lower()
            for allergen in ["cá", "tôm", "cua", "hải sản", "fish", "shrimp", "crab", "seafood", "salmon"]:
                if allergen in name_lower:
                    print(f"    ⚠️ CẢNH BÁO: Phát hiện hải sản '{allergen}' trong {meal['name']}!")
    
    # Weekly diversity summary
    print("\n======================================================================")
    print("TÓM TẮT ĐA DẠNG HÓA THỰC ĐƠN")
    print("======================================================================")
    from collections import Counter
    all_food_names = []
    for dp in result["meal_plan"]:
        for m in dp["meals"]:
            all_food_names.append(m.get("name_vi") or m["name"].split(" (")[0])
    counts = Counter(all_food_names)
    for name, count in counts.most_common(10):
        print(f"  {name}: {count} lần")
        
else:
    print("\n[LỖI] Không thể tìm thấy thực đơn khả thi thỏa mãn tất cả các ràng buộc.")
