import os
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from .check_db import verify_database
from .services.food_search import search_foods as search_foods_index
from .services.health_forecaster import HealthForecaster
try:
    from backend.ml.nlp.intent_engine import IntentEngine
    from backend.app.services.meal_plan_pipeline import MealPlanPipeline
except ModuleNotFoundError:
    from ml.nlp.intent_engine import IntentEngine
    from app.services.meal_plan_pipeline import MealPlanPipeline

app = FastAPI(title="Nutri-Advisor AI Backend")

# Initialize the forecast service
try:
    forecaster = HealthForecaster()
except Exception as e:
    print(f"⚠️ WARNING: HealthForecaster initialization failed: {e}")
    forecaster = None

# Initialize the NLP engine
try:
    intent_engine = IntentEngine()
    intent_engine.ensure_ready()
except Exception as e:
    print(f"⚠️ WARNING: IntentEngine initialization failed: {e}")
    intent_engine = None

# Initialize the meal plan pipeline
try:
    meal_pipeline = MealPlanPipeline()
    meal_pipeline.initialize()
except Exception as e:
    print(f"⚠️ WARNING: MealPlanPipeline initialization failed: {e}")
    meal_pipeline = None


# Initialize K-Means User Segmentation service
try:
    from backend.ml.clustering.user_segmentation import UserSegmentation
    from backend.ml.clustering import UserProfile, MENU_TEMPLATES
except ModuleNotFoundError:
    from ml.clustering.user_segmentation import UserSegmentation
    from ml.clustering import UserProfile, MENU_TEMPLATES

segmentation = UserSegmentation(cache_dir="data/ml/clustering")
try:
    segmentation.load_cached_model("demo_segmentation")
    print("✅ UserSegmentation loaded demo_segmentation model")
except Exception as e:
    print(f"⚠️ WARNING: UserSegmentation model load failed: {e}")
    segmentation = None


def calculate_tdee(weight_kg: float, height_cm: float, age: int, gender: str, activity_level: str) -> float:
    # 1. Calculate BMR using Mifflin-St Jeor Formula
    if gender.lower() in ["male", "nam", "m"]:
        bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age + 5.0
    else:
        bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age - 161.0
        
    # 2. Map activity level to multiplier
    activity_map = {
        "sedentary": 1.2,
        "lightly active": 1.375,
        "moderately active": 1.55,
        "very active": 1.725
    }
    multiplier = activity_map.get(activity_level.lower(), 1.2)
    return bmr * multiplier


def attach_energy_balance_fields(profile: Dict[str, Any], age: int) -> Dict[str, Any]:
    weight_kg = float(profile["weight_kg"])
    height_cm = float(profile["height_cm"])
    activity = profile.get("physical_activity_level") or "Moderately Active"
    daily_cal = float(profile.get("daily_calorie_target") or 0.0)
    maintenance_calories = calculate_tdee(
        weight_kg=weight_kg,
        height_cm=height_cm,
        age=age,
        gender=profile.get("gender") or "male",
        activity_level=activity,
    )
    profile["maintenance_calories"] = round(maintenance_calories)
    profile["daily_caloric_surplus"] = round(daily_cal - maintenance_calories)
    return profile


class ForecastRequest(BaseModel):
    current_weight_kg: float = Field(..., ge=30, le=250, description="Current weight of the user in kg")
    height_cm: float = Field(..., ge=100, le=250, description="Height of the user in cm")
    gender: str = Field(..., pattern="^(M|F)$", description="Gender of the user ('M' or 'F')")
    physical_activity_level: str = Field(
        ...,
        pattern="^(Sedentary|Lightly Active|Moderately Active|Very Active)$",
        description="Physical activity level of the user"
    )
    daily_calories_consumed: float = Field(..., ge=0, le=10000, description="Daily calories consumed in kcal")
    daily_caloric_surplus: float = Field(..., ge=-5000, le=5000, description="Daily caloric surplus or deficit in kcal")
    sleep_quality: str = Field(
        ...,
        pattern="^(Poor|Fair|Good|Excellent)$",
        description="Sleep quality of the user"
    )
    stress_level: float = Field(..., ge=1, le=10, description="Stress level from 1 to 10")


def _get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return db_url


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _component_total_cost_vnd(component: Dict[str, Any]) -> float:
    if component.get("total_cost_vnd") is not None:
        return _as_float(component.get("total_cost_vnd"))
    price_100g = _as_float(component.get("cost_vnd_100g"))
    weight_g = _as_float(component.get("weight"), 100.0)
    return price_100g * weight_g / 100.0


def _meal_total_cost_vnd(meal: Dict[str, Any]) -> float:
    if meal.get("total_cost_vnd") is not None:
        return _as_float(meal.get("total_cost_vnd"))
    components = meal.get("components") or []
    if components:
        return sum(_component_total_cost_vnd(c) for c in components if isinstance(c, dict))
    return _as_float(meal.get("cost_vnd_100g") or meal.get("price_100g_vnd"))


def _aggregate_components(components: List[Dict[str, Any]]) -> Dict[str, float]:
    valid_components = [c for c in components if isinstance(c, dict)]
    return {
        "calories": sum(_as_float(c.get("calories")) for c in valid_components),
        "protein": sum(_as_float(c.get("protein")) for c in valid_components),
        "fat": sum(_as_float(c.get("fat")) for c in valid_components),
        "carbs": sum(_as_float(c.get("carbs")) for c in valid_components),
        "total_cost_vnd": sum(_component_total_cost_vnd(c) for c in valid_components),
    }


def _build_meal_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    import json

    comps = []
    if row.get("notes"):
        try:
            comps = json.loads(row["notes"])
        except Exception:
            comps = []
    if not comps:
        comps = [{
            "food_id": int(row["food_id"]),
            "name": row["name_vi"],
            "weight": 100.0,
            "calories": float(row["energy_kcal"]),
            "protein": float(row["protein_g"]),
            "fat": float(row["fat_g"]),
            "carbs": float(row["carbs_g"]),
            "cost_vnd_100g": float(row["price_100g_vnd"])
        }]
    meal_totals = _aggregate_components(comps)
    meal_name = " + ".join(
        f"{c.get('name', row['name_vi'])} ({int(_as_float(c.get('weight'), 100.0))}g)"
        for c in comps
        if isinstance(c, dict)
    ) or row["name_vi"]
    return {
        "meal_type": row["meal_slot_code"],
        "food_id": row["food_id"],
        "name": meal_name,
        "calories": meal_totals["calories"],
        "protein": meal_totals["protein"],
        "fat": meal_totals["fat"],
        "carbs": meal_totals["carbs"],
        "total_cost_vnd": meal_totals["total_cost_vnd"],
        "components": comps
    }


def _load_user_meal_plan(user_id: int) -> List[Dict[str, Any]]:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    with psycopg2.connect(_get_database_url()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT mp.plan_date::text as plan_date, mp.meal_slot_code, mp.food_id, mp.notes,
                       f.name_vi, g.group_code as category, n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g,
                       COALESCE(f.price_100g_vnd, 15000) as price_100g_vnd
                FROM meal_plans mp
                JOIN foods f ON mp.food_id = f.food_id
                JOIN food_groups g ON f.food_group_id = g.food_group_id
                JOIN food_nutrients n ON f.food_id = n.food_id
                WHERE mp.user_id = %s
                ORDER BY
                    mp.plan_date,
                    CASE mp.meal_slot_code
                        WHEN 'breakfast' THEN 1
                        WHEN 'lunch' THEN 2
                        WHEN 'snack' THEN 3
                        WHEN 'dinner' THEN 4
                        ELSE 99
                    END;
            """, [user_id])
            rows = cur.fetchall()

    meal_plan = []
    if rows:
        dates = sorted(list(set(r["plan_date"] for r in rows)))
        days_of_week = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
        for idx, d_str in enumerate(dates):
            day_meals = [_build_meal_from_row(r) for r in rows if r["plan_date"] == d_str]
            meal_plan.append({
                "day": idx + 1,
                "day_name": days_of_week[idx % 7],
                "date": d_str,
                "meals": day_meals
            })
    return meal_plan


# Verify database on startup
print("\n[STARTUP] Initializing application...")
if not verify_database():
    print("\n⚠️  WARNING: Database verification failed. Some features may not work.")
    print("    Please check if PostgreSQL is running and SQL scripts have been executed.\n")





@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/foods/search")
def search_foods(
    q: str = Query(..., min_length=1, description="Food name keyword"),
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    try:
        return search_foods_index(query=q.strip(), limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Food search failed: {exc}")


@app.post("/api/v1/forecast")
def get_health_forecast(req: ForecastRequest) -> Dict[str, Any]:
    if not forecaster:
        raise HTTPException(
            status_code=503,
            detail="Health prediction service is currently unavailable. Please verify model file."
        )
    try:
        data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
        return forecaster.predict_weekly_trend(data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class LoginRequest(BaseModel):
    email: str


class ProfileRequest(BaseModel):
    full_name: str
    email: str
    gender: str
    age: int
    height_cm: float
    weight_kg: float
    daily_calorie_target: int
    budget_vnd_max: int
    physical_activity_level: str
    sleep_quality: str
    stress_level: int
    allergies: List[str] = []
    weight_goal: str = "maintain"


class SwapRequest(BaseModel):
    email: str
    plan_date: str
    meal_slot_code: str
    original_food_id: int
    replacement_food_id: int


class RegenerateMealPlanRequest(BaseModel):
    email: str


class ChatRequest(BaseModel):
    message: str = Field(..., description="User's natural language input query")
    user_profile: Dict[str, Any] = Field(default=None, description="Optional user profile details")


@app.post("/api/v1/chat")
def handle_chat(req: ChatRequest) -> Dict[str, Any]:
    if not intent_engine:
        raise HTTPException(
            status_code=503,
            detail="Chat intent engine is currently unavailable."
        )
    
    try:
        # Enforce intent guardrails (Format 2 rejection handled inside predict_chat_intent)
        intent_res = intent_engine.predict_chat_intent(req.message)
        if intent_res.get("status") == "rejected":
            return intent_res
            
        chat_intent = intent_res.get("intent")
        entities = intent_res.get("entities") or {}
        
        # Route based on the determined intent
        if chat_intent == "SUGGEST_MEAL":
            if not meal_pipeline:
                raise HTTPException(
                    status_code=503,
                    detail="Meal recommendation service is currently unavailable."
                )
            # Create profile from request user_profile, falling back to default target and macro ratios
            profile = (req.user_profile or {}).copy()
            # If entities extracted target calories or goal, apply them
            if entities.get("calories") is not None:
                profile["daily_calorie_target"] = entities["calories"]
            if entities.get("health_goal") != "unknown":
                profile["goal"] = entities["health_goal"]
            if entities.get("budget_vnd") is not None:
                profile["budget_vnd_max"] = entities["budget_vnd"]
            if entities.get("allergies"):
                profile["allergies"] = entities["allergies"]
            if entities.get("dietary_restrictions"):
                profile["dietary_restrictions"] = entities["dietary_restrictions"]
                
            # If no target calorie is specified anywhere, fallback to standard 2000 kcal
            if "daily_calorie_target" not in profile:
                profile["daily_calorie_target"] = 2000.0
                
            profile["exclude_snacks"] = True
            
            # Generate the meal plan (which is a 7-day schedule)
            plan = meal_pipeline.generate_meal_plan(profile)
            if not plan.get("feasible"):
                return {
                    "status": "success",
                    "intent": "SUGGEST_MEAL",
                    "feasible": False,
                    "reply": "Rất tiếc, NutriAdvisor không tìm thấy thực đơn phù hợp với các yêu cầu và ràng buộc về calo hoặc ngân sách của bạn lúc này."
                }
            
            # Extract the meals from Day 1 to serve as the single meal/day recommendation
            suggested_meals = plan["meal_plan"][0]["meals"]
            total_cal = sum(m.get("calories", 0.0) for m in suggested_meals)
            total_cost = sum(_meal_total_cost_vnd(m) for m in suggested_meals)
            
            return {
                "status": "success",
                "intent": "SUGGEST_MEAL",
                "feasible": True,
                "meals": suggested_meals,
                "total_calories": round(total_cal, 2),
                "total_cost": round(total_cost, 2),
                "reply": "Dưới đây là gợi ý thực đơn phù hợp cho bạn:"
            }
            
        elif chat_intent == "QUERY_NUTRITION":
            # Search database for food items extracted
            food_items = entities.get("food_items", [])
            # Fallback to searching the query itself if no specific food items were parsed
            search_queries = food_items if food_items else [req.message]
            
            found_foods = []
            for item_query in search_queries:
                search_res = search_foods_index(query=item_query.strip(), limit=3)
                if search_res.get("items"):
                    found_foods.extend(search_res["items"])
                    
            if not found_foods:
                return {
                    "status": "success",
                    "intent": "QUERY_NUTRITION",
                    "found": False,
                    "reply": f"NutriAdvisor không tìm thấy thông tin dinh dưỡng cho '{', '.join(search_queries)}' trong cơ sở dữ liệu."
                }
            
            # Expose standard macro profile of matched items
            return {
                "status": "success",
                "intent": "QUERY_NUTRITION",
                "found": True,
                "foods": found_foods[:5],
                "reply": "Dưới đây là thông tin dinh dưỡng của món ăn bạn tìm kiếm:"
            }
            
        elif chat_intent == "FIND_ALTERNATIVE":
            target = entities.get("replacement_target")
            if not target:
                # Fallback check
                food_items = entities.get("food_items", [])
                target = food_items[0] if food_items else req.message
                
            # Perform search to resolve target name to a food_id
            search_res = search_foods_index(query=target.strip(), limit=1)
            if not search_res.get("items"):
                return {
                    "status": "success",
                    "intent": "FIND_ALTERNATIVE",
                    "found": False,
                    "reply": f"Không tìm thấy món ăn '{target}' trong danh sách thực phẩm để tìm kiếm giải pháp thay thế."
                }
                
            matched_food = search_res["items"][0]
            food_id = int(matched_food["food_id"])
            
            if not meal_pipeline:
                raise HTTPException(
                    status_code=503,
                    detail="Meal recommendation service is currently unavailable."
                )
                
            # Request 5 similar foods using KNN
            replacements = meal_pipeline.find_replacement(
                food_id=food_id,
                user_profile=req.user_profile or {},
                n=5
            )
            
            return {
                "status": "success",
                "intent": "FIND_ALTERNATIVE",
                "found": True,
                "target_food": {
                    "food_id": food_id,
                    "name_vi": matched_food.get("name_vi"),
                    "canonical_key": matched_food.get("canonical_key")
                },
                "replacements": replacements,
                "reply": f"Dưới đây là danh sách các món ăn thay thế tương đương dinh dưỡng cho '{matched_food.get('name_vi')}':"
            }
            
        else:
            # Fallback to rejected OUT_OF_SCOPE format
            return {
                "status": "rejected",
                "intent": "OUT_OF_SCOPE",
                "reply": "NutriAdvisor hiện tại chỉ hỗ trợ các chức năng: (1) Gợi ý thực đơn nhanh, (2) Tra cứu dinh dưỡng món ăn, và (3) Tìm món thay thế tương đương. Câu hỏi của bạn không nằm trong phạm vi hỗ trợ của hệ thống."
            }
            
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/login")
def handle_login(req: LoginRequest) -> Dict[str, Any]:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        email = req.email.strip().lower()
        
        with psycopg2.connect(_get_database_url()) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch user profile
                cur.execute("""
                    SELECT user_id, full_name, email, gender, birth_year, height_cm, weight_kg, bmi, 
                           allergies, weight_goal, daily_calorie_target, budget_vnd_max, 
                           physical_activity_level, sleep_quality, stress_level
                    FROM user_profiles 
                    WHERE email = %s;
                """, [email])
                profile = cur.fetchone()
                
                if not profile:
                    return {"status": "new_user"}
                
                # Convert birth_year to age
                import datetime
                current_year = datetime.datetime.now().year
                age = current_year - profile["birth_year"] if profile["birth_year"] else 20
                profile["age"] = age
                
                # Convert memory types to float for JSON compatibility
                for key in ["height_cm", "weight_kg", "bmi"]:
                    if profile[key] is not None:
                        profile[key] = float(profile[key])
                attach_energy_balance_fields(profile, age)
                
                # 2. Fetch active 7-day meal plan
                cur.execute("""
                    SELECT mp.plan_date::text as plan_date, mp.meal_slot_code, mp.food_id, mp.notes,
                           f.name_vi, g.group_code as category, n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g,
                           COALESCE(f.price_100g_vnd, 15000) as price_100g_vnd
                    FROM meal_plans mp
                    JOIN foods f ON mp.food_id = f.food_id
                    JOIN food_groups g ON f.food_group_id = g.food_group_id
                    JOIN food_nutrients n ON f.food_id = n.food_id
                    WHERE mp.user_id = %s
                    ORDER BY
                        mp.plan_date,
                        CASE mp.meal_slot_code
                            WHEN 'breakfast' THEN 1
                            WHEN 'lunch' THEN 2
                            WHEN 'snack' THEN 3
                            WHEN 'dinner' THEN 4
                            ELSE 99
                        END;
                """, [profile["user_id"]])
                rows = cur.fetchall()
                
                meal_plan = []
                if rows:
                    dates = sorted(list(set(r["plan_date"] for r in rows)))
                    days_of_week = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
                    for idx, d_str in enumerate(dates):
                        day_name = days_of_week[idx % 7]
                        day_meals = []
                        for r in rows:
                            if r["plan_date"] == d_str:
                                import json
                                comps = []
                                if r["notes"]:
                                    try:
                                        comps = json.loads(r["notes"])
                                    except Exception:
                                        comps = []
                                if not comps:
                                    comps = [{
                                        "food_id": int(r["food_id"]),
                                        "name": r["name_vi"],
                                        "weight": 100.0,
                                        "calories": float(r["energy_kcal"]),
                                        "protein": float(r["protein_g"]),
                                        "fat": float(r["fat_g"]),
                                        "carbs": float(r["carbs_g"]),
                                        "cost_vnd_100g": float(r["price_100g_vnd"])
                                    }]
                                meal_totals = _aggregate_components(comps)
                                meal_name = " + ".join(
                                    f"{c.get('name', r['name_vi'])} ({int(_as_float(c.get('weight'), 100.0))}g)"
                                    for c in comps
                                    if isinstance(c, dict)
                                ) or r["name_vi"]
                                day_meals.append({
                                    "meal_type": r["meal_slot_code"],
                                    "food_id": r["food_id"],
                                    "name": meal_name,
                                    "calories": meal_totals["calories"],
                                    "protein": meal_totals["protein"],
                                    "fat": meal_totals["fat"],
                                    "carbs": meal_totals["carbs"],
                                    "total_cost_vnd": meal_totals["total_cost_vnd"],
                                    "components": comps
                                })
                        meal_plan.append({
                            "day": idx + 1,
                            "day_name": day_name,
                            "date": d_str,
                            "meals": day_meals
                        })
                
                # 3. Generate ML Forecast if profile exists
                gender_code = 'M' if profile["gender"] in ['male', 'Nam'] else 'F'
                
                age = profile["age"]
                weight_kg = float(profile["weight_kg"])
                height_cm = float(profile["height_cm"])
                activity = profile["physical_activity_level"] or "Moderately Active"
                daily_cal = float(profile["daily_calorie_target"] or 2000.0)
                
                tdee = calculate_tdee(
                    weight_kg=weight_kg,
                    height_cm=height_cm,
                    age=age,
                    gender=profile["gender"] or "male",
                    activity_level=activity
                )
                surplus = daily_cal - tdee
                
                forecast_payload = {
                    "current_weight_kg": weight_kg,
                    "height_cm": height_cm,
                    "gender": gender_code,
                    "physical_activity_level": activity,
                    "daily_calories_consumed": daily_cal,
                    "daily_caloric_surplus": surplus,
                    "sleep_quality": profile["sleep_quality"] or "Good",
                    "stress_level": float(profile["stress_level"] or 5.0)
                }
                
                forecast_data = None
                if forecaster:
                    try:
                        forecast_data = forecaster.predict_weekly_trend(forecast_payload)
                    except Exception as fe:
                        print(f"Error forecasting on login: {fe}")
                
                return {
                    "status": "success",
                    "profile": profile,
                    "meal_plan": meal_plan,
                    "forecast": forecast_data
                }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/profile")
def handle_save_profile(req: ProfileRequest) -> Dict[str, Any]:
    try:
        import psycopg2
        import datetime
        from psycopg2.extras import RealDictCursor
        
        email = req.email.strip().lower()
        full_name = req.full_name.strip()
        gender = req.gender.strip()
        age = req.age
        height_cm = req.height_cm
        weight_kg = req.weight_kg
        daily_calorie_target = req.daily_calorie_target
        budget_vnd_max = req.budget_vnd_max
        physical_activity_level = req.physical_activity_level.strip()
        sleep_quality = req.sleep_quality.strip()
        stress_level = req.stress_level
        allergies = req.allergies
        weight_goal = req.weight_goal.strip()
        
        current_year = datetime.datetime.now().year
        birth_year = current_year - age
        
        with psycopg2.connect(_get_database_url()) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT daily_calorie_target, budget_vnd_max, physical_activity_level, allergies, weight_goal
                    FROM user_profiles
                    WHERE email = %s;
                """, [email])
                existing_profile = cur.fetchone()

                cur.execute("""
                    INSERT INTO user_profiles (
                        full_name, email, gender, birth_year, height_cm, weight_kg, 
                        daily_calorie_target, weight_goal, budget_vnd_max, 
                        physical_activity_level, sleep_quality, stress_level, allergies
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO UPDATE SET
                        full_name = EXCLUDED.full_name,
                        gender = EXCLUDED.gender,
                        birth_year = EXCLUDED.birth_year,
                        height_cm = EXCLUDED.height_cm,
                        weight_kg = EXCLUDED.weight_kg,
                        daily_calorie_target = EXCLUDED.daily_calorie_target,
                        weight_goal = EXCLUDED.weight_goal,
                        budget_vnd_max = EXCLUDED.budget_vnd_max,
                        physical_activity_level = EXCLUDED.physical_activity_level,
                        sleep_quality = EXCLUDED.sleep_quality,
                        stress_level = EXCLUDED.stress_level,
                        allergies = EXCLUDED.allergies,
                        updated_at = NOW()
                    RETURNING user_id;
                """, [full_name, email, gender, birth_year, height_cm, weight_kg, 
                      daily_calorie_target, weight_goal, budget_vnd_max, 
                      physical_activity_level, sleep_quality, stress_level, allergies])
                user_id = cur.fetchone()["user_id"]
                conn.commit()
                
                cur.execute("""
                    SELECT user_id, full_name, email, gender, birth_year, height_cm, weight_kg, bmi, 
                           allergies, weight_goal, daily_calorie_target, budget_vnd_max, 
                           physical_activity_level, sleep_quality, stress_level
                    FROM user_profiles 
                    WHERE user_id = %s;
                """, [user_id])
                profile_data = cur.fetchone()
                profile_data["age"] = age
                for key in ["height_cm", "weight_kg", "bmi"]:
                    if profile_data[key] is not None:
                        profile_data[key] = float(profile_data[key])
                attach_energy_balance_fields(profile_data, age)
        meal_plan = _load_user_meal_plan(user_id)
        meal_fields_changed = True
        if existing_profile:
            meal_fields_changed = (
                int(existing_profile.get("daily_calorie_target") or 0) != int(daily_calorie_target)
                or int(existing_profile.get("budget_vnd_max") or 0) != int(budget_vnd_max)
                or str(existing_profile.get("physical_activity_level") or "") != physical_activity_level
                or str(existing_profile.get("weight_goal") or "") != weight_goal
                or sorted(existing_profile.get("allergies") or []) != sorted(allergies or [])
            )
        meal_plan_stale = meal_fields_changed or not meal_plan
        
        tdee = calculate_tdee(
            weight_kg=float(weight_kg),
            height_cm=float(height_cm),
            age=age,
            gender=gender,
            activity_level=physical_activity_level
        )
        surplus = float(daily_calorie_target) - tdee

        gender_code = 'M' if gender in ['male', 'Nam'] else 'F'
        forecast_payload = {
            "current_weight_kg": float(weight_kg),
            "height_cm": float(height_cm),
            "gender": gender_code,
            "physical_activity_level": physical_activity_level,
            "daily_calories_consumed": float(daily_calorie_target),
            "daily_caloric_surplus": surplus,
            "sleep_quality": sleep_quality,
            "stress_level": float(stress_level)
        }
        
        forecast_data = None
        if forecaster:
            try:
                forecast_data = forecaster.predict_weekly_trend(forecast_payload)
            except Exception as fe:
                print(f"Error forecasting: {fe}")
                
        return {
            "status": "success",
            "profile": profile_data,
            "meal_plan": meal_plan,
            "forecast": forecast_data,
            "meal_plan_stale": meal_plan_stale
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/meal-plan/regenerate")
def regenerate_meal_plan(req: RegenerateMealPlanRequest) -> Dict[str, Any]:
    if not meal_pipeline:
        raise HTTPException(status_code=503, detail="Meal recommendation service is unavailable.")

    try:
        import datetime
        import json
        import psycopg2
        from psycopg2.extras import RealDictCursor

        email = req.email.strip().lower()
        with psycopg2.connect(_get_database_url()) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT user_id, full_name, gender, birth_year, height_cm, weight_kg,
                           allergies, weight_goal, daily_calorie_target, budget_vnd_max,
                           physical_activity_level
                    FROM user_profiles
                    WHERE email = %s;
                """, [email])
                profile = cur.fetchone()
        if not profile:
            raise HTTPException(status_code=404, detail="User not found")

        current_year = datetime.datetime.now().year
        age = current_year - profile["birth_year"] if profile["birth_year"] else 20
        goal_raw = str(profile["weight_goal"] or "maintain").lower()
        if "lose" in goal_raw or "loss" in goal_raw:
            health_goal = "weight_loss"
        elif "gain" in goal_raw or "muscle" in goal_raw:
            health_goal = "muscle_gain"
        else:
            health_goal = "maintenance"

        segment_name = "balanced_lifestyle"
        if segmentation:
            try:
                user_p = UserProfile(
                    user_id=profile["user_id"],
                    age=age,
                    weight_kg=float(profile["weight_kg"]),
                    height_cm=float(profile["height_cm"]),
                    daily_calorie_target=int(profile["daily_calorie_target"]),
                    health_goal=health_goal,
                    allergies=profile["allergies"] or []
                )
                assignment = segmentation.predict(user_p)
                segment_name = assignment.segment_name
            except Exception as e:
                print(f"Error predicting user segment: {e}")

        if profile["physical_activity_level"] == "Very Active" or "gym" in str(profile["full_name"] or "").lower():
            segment_name = "performance_athlete"

        template = MENU_TEMPLATES.get(segment_name, MENU_TEMPLATES["balanced_lifestyle"])
        csp_profile = {
            "daily_calorie_target": float(profile["daily_calorie_target"]),
            "budget_vnd_max": float(profile["budget_vnd_max"]),
            "macro_ratios": {
                "protein": template["protein_target_ratio"],
                "fat": template["fat_target_ratio"],
                "carbs": template["carbs_target_ratio"]
            },
            "exclude_snacks": True,
            "allergies": profile["allergies"] or []
        }

        plan_res = meal_pipeline.generate_meal_plan(csp_profile)
        if not plan_res.get("feasible") or not plan_res.get("meal_plan"):
            return {"status": "infeasible", "meal_plan": [], "meal_plan_stale": True}

        with psycopg2.connect(_get_database_url()) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM meal_plans WHERE user_id = %s;", [profile["user_id"]])
                for idx, day_data in enumerate(plan_res["meal_plan"]):
                    plan_date = datetime.date.today() + datetime.timedelta(days=idx)
                    for m in day_data["meals"]:
                        cur.execute("""
                            INSERT INTO meal_plans (user_id, food_id, plan_date, meal_slot_code, portion_multiplier, generated_by, notes)
                            VALUES (%s, %s, %s, %s, 1.00, 'csp', %s)
                            ON CONFLICT (user_id, plan_date, meal_slot_code) DO UPDATE SET
                                food_id = EXCLUDED.food_id,
                                generated_by = EXCLUDED.generated_by,
                                notes = EXCLUDED.notes;
                        """, [
                            profile["user_id"],
                            m["food_id"],
                            plan_date,
                            m["meal_type"],
                            json.dumps(m.get("components", []))
                        ])
                conn.commit()

        return {
            "status": "success",
            "meal_plan": _load_user_meal_plan(profile["user_id"]),
            "meal_plan_stale": False
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/v1/meal-plan/swap")
def handle_swap_meal(req: SwapRequest) -> Dict[str, Any]:
    try:
        import psycopg2
        import json
        
        email = req.email.strip().lower()
        plan_date = req.plan_date
        meal_slot_code = req.meal_slot_code
        original_food_id = req.original_food_id
        replacement_food_id = req.replacement_food_id
        
        with psycopg2.connect(_get_database_url()) as conn:
            with conn.cursor() as cur:
                # 1. Resolve user email to user_id
                cur.execute("SELECT user_id FROM user_profiles WHERE email = %s;", [email])
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="User not found")
                user_id = row[0]
                
                # 2. Get current meal record details
                cur.execute("""
                    SELECT food_id, notes 
                    FROM meal_plans 
                    WHERE user_id = %s AND plan_date = %s AND meal_slot_code = %s;
                """, [user_id, plan_date, meal_slot_code])
                meal_row = cur.fetchone()
                
                if not meal_row:
                    raise HTTPException(status_code=404, detail="Meal slot record not found")
                
                db_food_id, db_notes = meal_row
                
                # 3. Parse components JSON list
                comps = []
                if db_notes:
                    try:
                        comps = json.loads(db_notes)
                    except Exception:
                        comps = []
                
                # Fallback to single component if notes was missing or corrupted
                if not comps:
                    cur.execute("""
                        SELECT f.name_vi, n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g, COALESCE(f.price_100g_vnd, 15000)
                        FROM foods f
                        JOIN food_nutrients n ON f.food_id = n.food_id
                        WHERE f.food_id = %s;
                    """, [db_food_id])
                    orig_row = cur.fetchone()
                    if orig_row:
                        name_vi, energy, protein, fat, carbs, price = orig_row
                        comps = [{
                            "food_id": int(db_food_id),
                            "name": name_vi,
                            "weight": 100.0,
                            "calories": float(energy or 0),
                            "protein": float(protein or 0),
                            "fat": float(fat or 0),
                            "carbs": float(carbs or 0),
                            "cost_vnd_100g": float(price)
                        }]
                
                # 4. Fetch replacement food info from database
                cur.execute("""
                    SELECT f.name_vi, n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g, COALESCE(f.price_100g_vnd, 15000)
                    FROM foods f
                    JOIN food_nutrients n ON f.food_id = n.food_id
                    WHERE f.food_id = %s;
                """, [replacement_food_id])
                rep_row = cur.fetchone()
                
                if not rep_row:
                    raise HTTPException(status_code=404, detail="Replacement food not found")
                
                rep_name, rep_kcal, rep_prot, rep_fat, rep_carbs, rep_price = rep_row
                rep_display = rep_name
                for suffix in [" nguyên chất", " tươi", " sống", " chín", " luộc", " khô", ", tươi", ", sống", ", chín", ", luộc", ", khô", ", raw"]:
                    if rep_display.lower().endswith(suffix):
                        rep_display = rep_display[:-len(suffix)].strip()
                
                # 5. Swap the target component in the comps list
                swapped = False
                for idx, c in enumerate(comps):
                    if int(c["food_id"]) == int(original_food_id):
                        weight = float(c.get("weight", 100.0))
                        factor = weight / 100.0
                        
                        comps[idx] = {
                            "food_id": int(replacement_food_id),
                            "name": rep_display,
                            "weight": weight,
                            "calories": float(rep_kcal or 0) * factor,
                            "protein": float(rep_prot or 0) * factor,
                            "fat": float(rep_fat or 0) * factor,
                            "carbs": float(rep_carbs or 0) * factor,
                            "cost_vnd_100g": float(rep_price)
                        }
                        swapped = True
                        break
                
                if not swapped:
                    # If target food not found in comps list, just push it or fail
                    raise HTTPException(status_code=400, detail="Original food item not found in slot components")
                
                # 6. Determine main food_id of the row
                main_food_id = comps[0]["food_id"]
                notes_data = json.dumps(comps)
                
                # 7. Update meal_plans in DB
                cur.execute("""
                    UPDATE meal_plans 
                    SET food_id = %s, notes = %s, generated_by = 'knn'
                    WHERE user_id = %s AND plan_date = %s AND meal_slot_code = %s;
                """, [main_food_id, notes_data, user_id, plan_date, meal_slot_code])
                conn.commit()
                
        return {"status": "success", "message": "Meal component swapped successfully"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/v1/food/{food_id}/alternatives")
def get_food_alternatives(food_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    if not meal_pipeline:
        raise HTTPException(status_code=503, detail="Meal recommendation service is currently unavailable.")
    try:
        return meal_pipeline.find_replacement(food_id=food_id, user_profile={}, n=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# Configure frontend static file serving
import os

FRONTEND_DIR = None
for path in ["frontend", "../frontend", "/app/frontend"]:
    if os.path.isdir(path):
        FRONTEND_DIR = os.path.abspath(path)
        break

if FRONTEND_DIR:
    assets_dir = os.path.join(FRONTEND_DIR, "assets")
    if os.path.isdir(assets_dir):
        try:
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
            print(f"✅ Mounted /assets from {assets_dir}")
        except Exception as e:
            print(f"⚠️ WARNING: StaticFiles mount failed: {e}")
    else:
        print(f"⚠️ WARNING: assets directory not found in {FRONTEND_DIR}")
else:
    print("⚠️ WARNING: frontend directory not found in any standard location.")


@app.get("/")
def read_root():
    if FRONTEND_DIR:
        index_path = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
    return {"message": "Nutri-Advisor backend is running (frontend assets not yet ready)"}


