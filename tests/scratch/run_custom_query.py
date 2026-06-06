import os
import dotenv

# Force offline local database fallback
dotenv.load_dotenv()
os.environ["DATABASE_URL"] = ""

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

user_message = "Hãy gợi ý cho tôi thực đơn 3000 calo cho người tập gym trong khoảng giá 300k một ngày"
print(f"\n[Người dùng nhắn]: \"{user_message}\"")

# Predict intent and convert to structured parameters
nlp_result = engine.predict(user_message)
print(f"- Ý định dự đoán (Intent): {nlp_result.intent} (Độ tin cậy: {nlp_result.confidence:.2f})")
print(f"- Các thực thể trích xuất được (Entities):")
print(f"  + Calo mục tiêu: {nlp_result.entities.get('calories') or '3000 (Ghi đè)'} kcal")
print(f"  + Ngân sách tối đa: {nlp_result.entities.get('budget_vnd_max') or '300000 (Ghi đè)'} VND")
print(f"  + Thành phần loại trừ: {nlp_result.entities.get('exclude') or []}")

# Build user profile for CSP Solver
user_profile = {
    "daily_calorie_target": 3000,
    "macro_ratios": {"protein": 0.35, "fat": 0.25, "carbs": 0.40}, # Protein-rich ratio for gym goers
    "allergies": nlp_result.entities.get("exclude") or [],
    "budget_vnd_max": 300000,
    "exclude_snacks": True,
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
    print("CHI TIẾT THỰC ĐƠN 7 NGÀY CHO NGƯỜI TẬP GYM (3000 kcal - 300k VND/ngày)")
    print("======================================================================")
    
    for day_idx, day_plan in enumerate(result["meal_plan"], start=1):
        total_calories = sum(m.get("calories", 0) for m in day_plan["meals"])
        estimated_cost_vnd = sum(m.get("cost_vnd_100g", 15000) for m in day_plan["meals"])
        
        print(f"\n[NGÀY {day_idx}]")
        print(f"  - Tổng calo thực tế: {total_calories:.1f} kcal / {user_profile['daily_calorie_target']} kcal")
        print(f"  - Chi phí ước tính: {estimated_cost_vnd:,.0f} VND")
        print(f"  - Chi tiết các bữa ăn:")
        
        for meal in day_plan["meals"]:
            meal_type_vi = {
                "breakfast": "Bữa sáng",
                "lunch": "Bữa trưa",
                "snack": "Bữa phụ",
                "dinner": "Bữa tối"
            }.get(meal["meal_type"], meal["meal_type"])
            
            print(f"    + {meal_type_vi:<10}: {meal['name']}")
            print(f"      {"":<10}  | Calo: {meal.get('calories', 0):.1f} kcal | Protein: {meal.get('protein', 0):.1f}g | Fat: {meal.get('fat', 0):.1f}g | Carbs: {meal.get('carbs', 0):.1f}g")
else:
    print("\n[LỖI] Không thể tìm thấy thực đơn khả thi thỏa mãn tất cả các ràng buộc.")
