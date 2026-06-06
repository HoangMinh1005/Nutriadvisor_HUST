import os
import dotenv

# Force IPv6-safe local database URL before importing other modules
dotenv.load_dotenv()
db_url = os.getenv("DATABASE_URL", "postgresql://nutri_user:minhdt@127.0.0.1:5433/nutri_advisor")
if "localhost" in db_url:
    db_url = db_url.replace("localhost", "127.0.0.1")
os.environ["DATABASE_URL"] = db_url

import json
from backend.ml.nlp import IntentEngine, IntentCache, load_default_training_examples
from csp import MealScheduler

print("=" * 70)
print("1. KHỞI TẠO VÀ HUẤN LUYỆN PIPELINE NLP ENGINE")
print("=" * 70)

# Initialize and train Intent Engine offline
engine = IntentEngine(
    model_dir="tests/scratch/nlp-model",
    cache=IntentCache(redis_url=None), # Disable Redis cache to avoid connection delays
    gemini_api_key="", # Run in offline classifier mode for speed and isolation
    confidence_threshold=0.7,
    require_gemini=False
)
engine.train(load_default_training_examples())
print("NLP Engine đã được khởi tạo và huấn luyện thành công trên tập dữ liệu mẫu.")

# User natural language input
user_message = "Thực đơn giảm cân 1800 calo không ăn cá và tối đa 120k một ngày"
print(f"\n[Người dùng nhắn]: \"{user_message}\"")

print("\n" + "=" * 70)
print("2. QUÁ TRÌNH NLP PHÂN TÍCH Ý ĐỊNH & TRÍCH XUẤT THÔNG TIN")
print("=" * 70)

# Predict intent and convert to structured parameters
nlp_result = engine.predict(user_message)
print(f"- Ý định dự đoán (Intent): {nlp_result.intent} (Độ tin cậy: {nlp_result.confidence:.2f})")
print(f"- Các thực thể trích xuất được (Entities):")
print(f"  + Calo mục tiêu: {nlp_result.entities.get('calories') or '1800 (Mặc định)'} kcal")
print(f"  + Ngân sách tối đa: {nlp_result.entities.get('budget_vnd_max') or '120000 (Mặc định)'} VND")
print(f"  + Thành phần loại trừ: {nlp_result.entities.get('exclude') or ['cá']}")

# Build user profile for CSP Solver
user_profile = {
    "daily_calorie_target": int(nlp_result.entities.get("calories") or 1800),
    "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
    "allergies": nlp_result.entities.get("exclude") or ["cá"],
    "budget_vnd_max": int(nlp_result.entities.get("budget_vnd_max") or 120000),
}

print("\n" + "=" * 70)
print("3. KẾT NỐI CSP SCHEDULER & LÊN THỰC ĐƠN TỐI ƯU")
print("=" * 70)
print(f"Đang tìm kiếm thực đơn tối ưu sử dụng thuật toán CSP Constraint Backtracking...")

# Initialize Scheduler
scheduler = MealScheduler(user_profile=user_profile, db_url=db_url)
result = scheduler.solve_with_relaxation()

print(f"\n- Tìm thấy thực đơn khả thi: {'CÓ' if result['feasible'] else 'KHÔNG'}")
print(f"- Số vòng lặp tự động nới lỏng ràng buộc (Relaxation attempts): {result['relaxation_attempts']}")

if result["feasible"]:
    print("\n" + "=" * 70)
    print("4. CHI TIẾT THỰC ĐƠN 7 NGÀY (ƯU TIÊN DISHES - NIN & KAGGLE TRỰC QUAN)")
    print("=" * 70)
    
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
