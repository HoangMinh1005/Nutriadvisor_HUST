import os
import sys
import dotenv

# Load environment variables
dotenv.load_dotenv()
sys.path.insert(0, ".")

from backend.app.services.meal_plan_pipeline import MealPlanPipeline


def main():
    print("============================================================")
    print("NUTRIADVISOR USER FLOW DEMONSTRATION (UPGRADED CSP)")
    print("============================================================\n")

    # 1. Initialize the Pipeline (cache-first startup)
    print("1. Initializing pipeline...")
    pipeline = MealPlanPipeline()
    pipeline.initialize(rebuild=True)
    print("Pipeline successfully initialized.\n")

    # 2. Define the User Profile
    # Yêu cầu đồng bộ: 200k/ngày, 1800 calo, carbs: 30%, fat: 30%, protein: 40%, không bữa phụ, không ăn hải sản
    user_profile = {
        "daily_calorie_target": 1800,
        "macro_ratios": {"protein": 0.40, "fat": 0.20, "carbs": 0.40},
        "budget_vnd_max": 200000,
        "exclude_snacks": True,
        "allergies": ["seafood", "hải sản"],
    }
    
    # Lấy các biến mục tiêu để hiển thị động
    target_p = user_profile['macro_ratios']['protein'] * 100
    target_f = user_profile['macro_ratios']['fat'] * 100
    target_c = user_profile['macro_ratios']['carbs'] * 100

    print("2. User Profile Targets:")
    print(f"   - Calories: {user_profile['daily_calorie_target']} kcal")
    print(f"   - Macro Ratios: Protein {target_p:.1f}%, Fat {target_f:.1f}%, Carbs {target_c:.1f}%")
    print(f"   - Daily Budget Limit: {user_profile['budget_vnd_max']:,} VND")
    print(f"   - Exclude Snacks: {user_profile['exclude_snacks']}")
    print(f"   - Allergies: {', '.join(user_profile['allergies'])}\n")

    # 3. Generate 7-Day Meal Plan
    print("3. Generating 7-day meal plan using KNN + CSP...")
    result = pipeline.generate_meal_plan(user_profile)

    if not result.get("feasible"):
        print("Failed to generate a feasible plan. Check solver settings/constraints.")
        return

    print("Success! Feasible meal plan generated.\n")
    print("============================================================")
    print("GENERATED 7-DAY MEAL PLAN (CULINARY STRUCTURE COMPLIANT):")
    print("============================================================")
    
    plan = result["meal_plan"]
    for day_plan in plan:
        day = day_plan["day"]
        print(f"\n--- DAY {day} ---")
        day_cal = 0.0
        day_cost = 0.0
        day_p = 0.0
        day_f = 0.0
        day_c = 0.0
        
        for meal in day_plan["meals"]:
            meal_type = meal["meal_type"].upper()
            name = meal["name"]
            cal = meal["calories"]
            # cost_vnd_100g lúc này đã là tổng chi phí thực tế (đã nhân hệ số weight_g / 100) của cả bữa ăn
            cost = meal["cost_vnd_100g"] 
            
            day_cal += cal
            day_cost += cost
            day_p += meal["protein"]
            day_f += meal["fat"]
            day_c += meal["carbs"]
            
            print(f"  [{meal_type}] {name} | {cal:.1f} kcal | {cost:,.0f} VND")
            
        # Tính toán chính xác tỷ lệ phân bổ vĩ mô (Macros) thực tế
        total_mass = day_p + day_f + day_c
        p_ratio = (day_p / total_mass * 100) if total_mass > 0 else 0
        f_ratio = (day_f / total_mass * 100) if total_mass > 0 else 0
        c_ratio = (day_c / total_mass * 100) if total_mass > 0 else 0
        
        print(f"  Summary: Total Cal={day_cal:.1f} kcal | Cost={day_cost:,.0f} VND")
        print(f"  Macros: Protein={p_ratio:.1f}% (target {target_p:.0f}%), Fat={f_ratio:.1f}% (target {target_f:.0f}%), Carbs={c_ratio:.1f}% (target {target_c:.0f}%)")

    print("\n============================================================")
    print("4. Demonstration of Replacing a Meal Component:")
    print("============================================================")
    
    # Lấy thông tin cấu phần đầu tiên của ngày đầu tiên để test tính năng thay thế món ăn tương đương
    sample_meal = plan[0]["meals"][0]
    sample_food_id = sample_meal["food_id"]
    # Tách chuỗi để lấy tên món ăn chính, loại bỏ phần text (Món Việt - NIN) và trọng lượng (g)
    sample_food_name = sample_meal["name"].split(" (")[0]
    
    print(f"Replacing '{sample_food_name}' (Food ID: {sample_food_id}) with nutrient-similar foods:")
    replacements = pipeline.find_replacement(sample_food_id, user_profile, n=3)
    
    for idx, rep in enumerate(replacements):
        name_display = rep.get("name_vi") or rep.get("name_en")
        score = rep.get("match_score", 0.0)
        print(f"  {idx + 1}. {name_display} (Food ID: {rep['food_id']}) | Match Score: {score:.2%}")
    print("============================================================\n")


if __name__ == "__main__":
    main()