"""Unit tests for the CSP Meal Planning Module."""
from __future__ import annotations

import random

import pytest

from csp import MealScheduler, NutrientConstraints


def test_nutrient_constraints_calories():
    constraints = NutrientConstraints(daily_calorie_target=1800.0, calorie_tolerance_pct=0.10)
    
    # Valid daily meals (total: 1810 kcal)
    valid_meals = [
        {"calories": 400},
        {"energy_kcal": 600},
        {"calories": 300},
        {"energy_kcal": 510},
    ]
    assert constraints.check_daily_calories(valid_meals) is True

    # Too high (total: 2100 kcal)
    high_meals = [
        {"calories": 500},
        {"calories": 700},
        {"calories": 400},
        {"calories": 500},
    ]
    assert constraints.check_daily_calories(high_meals) is False


def test_nutrient_constraints_allergies():
    constraints = NutrientConstraints(allergies=["peanut", "hải sản"])
    
    safe_meals = [
        {"canonical_name_en": "Chicken Breast", "name_vi": "ức gà", "category": "gia_cam"},
        {"canonical_name_en": "White Rice", "name_vi": "cơm trắng", "category": "tinh_bot"},
    ]
    assert constraints.check_allergies(safe_meals) is True

    allergic_meals = [
        {"canonical_name_en": "Peanut Butter", "name_vi": "bơ đậu phộng", "category": "hat"},
        {"canonical_name_en": "White Rice", "name_vi": "cơm trắng", "category": "tinh_bot"},
    ]
    assert constraints.check_allergies(allergic_meals) is False


def test_nutrient_constraints_weekly_diversity():
    constraints = NutrientConstraints(max_food_occurrences_per_week=2)
    
    # Food IDs with counts within max occurrence (2)
    valid_ids = [1, 2, 3, 4, 1, 2, 3, 4, 5, 6, 5, 6]
    assert constraints.check_weekly_diversity(valid_ids) is True

    # ID 1 appears 3 times
    invalid_ids = [1, 2, 3, 4, 1, 2, 3, 4, 1, 6]
    assert constraints.check_weekly_diversity(invalid_ids) is False


def test_scheduler_solve_offline_fallback():
    user = {
        "daily_calorie_target": 1000,
        "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
        "allergies": ["duck", "vịt"],  # Duck has food_id=10
        "budget_vnd_max": 100000,
    }
    
    scheduler = MealScheduler(user_profile=user, db_url="")
    result = scheduler.solve_with_relaxation()

    assert result["feasible"] is True
    assert len(result["meal_plan"]) == 7
    
    # Verify no meal contains duck
    for day in result["meal_plan"]:
        assert len(day["meals"]) == 4
        for meal in day["meals"]:
            assert "duck" not in str(meal.get("name")).lower()
            assert "vịt" not in str(meal.get("name")).lower()


def test_scheduler_solve_auto_relaxation():
    user = {
        "daily_calorie_target": 3000,  # Extreme calorie target for limited sample foods
        "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
        "budget_vnd_max": 2000,  # Extreme budget restriction
    }
    
    scheduler = MealScheduler(user_profile=user, db_url="")
    result = scheduler.solve_with_relaxation(max_attempts=3)
    
    # Due to extremely tight budget and calorie targets, it should trigger relaxation
    # and eventually complete successfully or gracefully handle the infeasibility
    assert result["relaxation_attempts"] > 1


def test_dietary_rules():
    # Rich mock data to trigger is_rich_db matching (>=1 carbs, >=1 proteins, >=1 fibers)
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
        # Additional carbs/proteins/fibers to satisfy minimum counts
        {"food_id": 11, "canonical_name_en": "Bread", "name_vi": "bánh mì", "calories": 265, "protein": 9, "fat": 3.2, "carbs": 49, "cost_vnd_100g": 5000, "category": "tinh_bột"},
        {"food_id": 12, "canonical_name_en": "Sweet Potato", "name_vi": "khoai lang", "calories": 86, "protein": 1.6, "fat": 0.1, "carbs": 20, "cost_vnd_100g": 3000, "category": "tinh_bột"},
        {"food_id": 13, "canonical_name_en": "Pork", "name_vi": "thịt heo", "calories": 242, "protein": 27, "fat": 14, "carbs": 0, "cost_vnd_100g": 14000, "category": "thịt_lợn"},
        {"food_id": 14, "canonical_name_en": "Spinach", "name_vi": "rau bó xôi", "calories": 23, "protein": 2.9, "fat": 0.4, "carbs": 3.6, "cost_vnd_100g": 4000, "category": "rau_xanh"},
        {"food_id": 15, "canonical_name_en": "Broccoli", "name_vi": "súp lơ xanh", "calories": 34, "protein": 2.8, "fat": 0.4, "carbs": 7, "cost_vnd_100g": 5000, "category": "rau_xanh"},
        {"food_id": 16, "canonical_name_en": "Brown Rice", "name_vi": "cơm lứt", "calories": 111, "protein": 2.6, "fat": 0.9, "carbs": 23, "cost_vnd_100g": 3000, "category": "tinh_bột"},
        # Standalone main dishes
        {"food_id": 17, "canonical_name_en": "Beef Pho", "name_vi": "Phở bò chín bình dân", "calories": 350, "protein": 15, "fat": 8, "carbs": 45, "cost_vnd_100g": 10000, "category": "món_chính"},
        {"food_id": 18, "canonical_name_en": "Stir-fried Noodles", "name_vi": "Mỳ xào thập cẩm", "calories": 400, "protein": 12, "fat": 15, "carbs": 50, "cost_vnd_100g": 12000, "category": "món_chính"},
        # Snacks
        {"food_id": 19, "canonical_name_en": "Dried Jackfruit", "name_vi": "Mít khô", "calories": 280, "protein": 2, "fat": 1, "carbs": 70, "cost_vnd_100g": 35000, "category": "đồ_ăn_vặt"},
        # Extra proteins for diversity across 7 days
        {"food_id": 20, "canonical_name_en": "Tuna", "name_vi": "cá ngừ tươi", "calories": 130, "protein": 28, "fat": 1.2, "carbs": 0, "cost_vnd_100g": 20000, "category": "cá_hải_sản"},
        {"food_id": 21, "canonical_name_en": "Shrimp", "name_vi": "tôm", "calories": 99, "protein": 24, "fat": 0.3, "carbs": 0.2, "cost_vnd_100g": 30000, "category": "cá_hải_sản"},
        {"food_id": 22, "canonical_name_en": "Morning Glory", "name_vi": "rau muống", "calories": 19, "protein": 2.6, "fat": 0.1, "carbs": 3.1, "cost_vnd_100g": 1000, "category": "rau_xanh"},
        {"food_id": 23, "canonical_name_en": "Nấm rơm", "name_vi": "nấm rơm", "calories": 35, "protein": 3.8, "fat": 0.5, "carbs": 4.0, "cost_vnd_100g": 8000, "category": "rau_xanh"},
    ]

    user = {
        "daily_calorie_target": 1800,
        "macro_ratios": {"protein": 0.3, "fat": 0.3, "carbs": 0.4},
        "budget_vnd_max": 250000,  # Generous budget for small dataset
    }
    
    # We pass the rich mock foods directly to the scheduler
    scheduler = MealScheduler(user_profile=user, available_foods=rich_mock_foods, db_url="")
    result = scheduler.solve_with_relaxation()

    assert result["feasible"] is True
    assert len(result["meal_plan"]) == 7
    
    for day in result["meal_plan"]:
        # Verify at least 3 slots (Breakfast, Lunch, Dinner) - may have 4 with snack
        assert len(day["meals"]) >= 3
        
        meals_by_type = {m["meal_type"]: m for m in day["meals"]}
        
        # 1. Main meals (Breakfast, Lunch, Dinner) contain NO snacks/desserts (Mít khô)
        for slot in ["breakfast", "lunch", "dinner"]:
            meal = meals_by_type[slot]
            assert "mít khô" not in meal["name"].lower()
            assert "đồ_ăn_vặt" not in meal.get("category", "").lower()
            
        # 2. Check standalone món_chính rule (no '+' in name if category is món_chính)
        for slot in ["breakfast", "lunch", "dinner"]:
            meal = meals_by_type[slot]
            if meal.get("category") == "món_chính":
                assert "+" not in meal["name"]


def test_calorie_distribution_constraint():
    constraints = NutrientConstraints(daily_calorie_target=3000.0)
    
    # 1. Perfectly distributed plan (total: 3000 kcal)
    # Breakfast: 750 (25%), Lunch: 1050 (35%), Dinner: 1200 (40%)
    valid_plan = [
        {"meal_type": "breakfast", "calories": 750},
        {"meal_type": "lunch", "calories": 1050},
        {"meal_type": "dinner", "calories": 1200},
    ]
    assert constraints.check_calorie_distribution(valid_plan) is True

    # 2. Extreme plan (Breakfast: 150 (5%), Lunch: 1350 (45%), Dinner: 1500 (50%))
    invalid_plan = [
        {"meal_type": "breakfast", "calories": 150},
        {"meal_type": "lunch", "calories": 1350},
        {"meal_type": "dinner", "calories": 1500},
    ]
    assert constraints.check_calorie_distribution(invalid_plan) is False


def test_gym_high_quality_protein_rules():
    from csp.scheduler import is_high_quality_protein
    # Verify that dried/powdered egg white is NOT treated as high quality protein
    dried_egg = {"name_vi": "Lòng trắng trứng sấy khô", "canonical_name_en": "Egg, dried, white", "category": "trứng"}
    assert is_high_quality_protein(dried_egg) is False

    # Fresh chicken breast is high quality
    fresh_chicken = {"name_vi": "ức gà tươi", "canonical_name_en": "Chicken breast, fresh", "category": "thịt_gia_cầm"}
    assert is_high_quality_protein(fresh_chicken) is True

    # Fresh egg is high quality (not dried/powdered)
    fresh_egg = {"name_vi": "trứng gà", "canonical_name_en": "Egg, whole", "category": "trứng"}
    assert is_high_quality_protein(fresh_egg) is True


def test_get_max_serving_g():
    from csp.scheduler import get_max_serving_g
    
    # Cheese should be 50g
    cheese = {"name_vi": "Phô mai tam giác", "category": "Các món trứng, sữa và chế phẩm"}
    assert get_max_serving_g(cheese) == 50.0

    # Cơm should be 300g
    com = {"name_vi": "Cơm trắng", "category": "tinh_bot"}
    assert get_max_serving_g(com) == 300.0

    # Powder should be 30g
    powder = {"name_vi": "Bột chuối sấy khô", "category": "trái_cây"}
    assert get_max_serving_g(powder) == 30.0

    # High-calorie plans should allow larger realistic portions
    assert get_max_serving_g(com, daily_calorie_target=2600) == 380.0
    assert get_max_serving_g(com, daily_calorie_target=3200) == 450.0

    chicken = {"name_vi": "Ức gà tươi", "category": "thịt_gia_cầm"}
    assert get_max_serving_g(chicken, is_gym=True, daily_calorie_target=3200) == 550.0


def test_high_calorie_plan_forces_snack_slot():
    scheduler = MealScheduler(
        {"daily_calorie_target": 2600, "exclude_snacks": True},
        available_foods=[],
        db_url=None,
    )
    assert scheduler._effective_exclude_snacks() is False


def test_restricted_high_calorie_plan_forces_snack_slot():
    scheduler = MealScheduler(
        {"daily_calorie_target": 2300, "exclude_snacks": True, "dietary_restrictions": ["halal"]},
        available_foods=[],
        db_url=None,
    )
    assert scheduler._effective_exclude_snacks() is False


def test_food_tagging():
    from csp.scheduler import get_dynamic_tags
    
    # Chicken breast -> clean_protein, role_protein, allergen_chicken
    gà_tags = get_dynamic_tags({"name_vi": "ức gà tươi", "canonical_name_en": "Chicken, breast, raw", "category": "gia_cam"})
    assert "clean_protein" in gà_tags
    assert "role_protein" in gà_tags
    assert "allergen_chicken" in gà_tags
    assert "allergen_seafood" not in gà_tags

    # Salmon -> allergen_seafood, role_protein, clean_protein
    cá_tags = get_dynamic_tags({"name_vi": "cá hồi tươi", "canonical_name_en": "Salmon, fillet, raw", "category": "hai_san"})
    assert "allergen_seafood" in cá_tags
    assert "role_protein" in cá_tags
    assert "clean_protein" in cá_tags
    
    # Milk -> allergen_milk, role_protein
    milk_tags = get_dynamic_tags({"name_vi": "Sữa tươi tiệt trùng", "canonical_name_en": "Milk, fluid", "category": "sua_che_pham"})
    assert "allergen_milk" in milk_tags
    assert "role_protein" in milk_tags
    assert "allergen_seafood" not in milk_tags


def test_dietary_restriction_filtering():
    from csp.classification import violates_dietary_restrictions

    chicken = {"name_vi": "ức gà tươi", "canonical_name_en": "Chicken breast", "category": "thịt_gia_cầm"}
    egg = {"name_vi": "trứng gà", "canonical_name_en": "Egg, whole", "category": "trứng"}
    tofu = {"name_vi": "đậu phụ", "canonical_name_en": "Tofu", "category": "đậu"}
    pork = {"name_vi": "thịt heo nạc", "canonical_name_en": "Pork lean", "category": "thịt_lợn"}

    assert violates_dietary_restrictions(chicken, ["vegetarian"]) is True
    assert violates_dietary_restrictions(egg, ["vegetarian"]) is False
    assert violates_dietary_restrictions(egg, ["vegan"]) is True
    assert violates_dietary_restrictions(tofu, ["vegan"]) is False
    assert violates_dietary_restrictions(pork, ["halal"]) is True

    fish_cake = {"name_vi": "Chả cá thác lác", "canonical_name_en": "Fish cake", "category": "cá_hải_sản"}
    fish_sauce = {"name_vi": "Nước mắm", "canonical_name_en": "Fish sauce", "category": "gia_vị"}
    cheese = {"name_vi": "Phô mai", "canonical_name_en": "Cheese", "category": "sữa"}
    pork_sausage = {"name_vi": "Giò lụa", "canonical_name_en": "Vietnamese pork sausage", "category": "món ăn chế biến"}
    pate = {"name_vi": "Pate gan heo", "canonical_name_en": "Pork liver pate", "category": "món ăn chế biến"}
    blood = {"name_vi": "Tiết luộc", "canonical_name_en": "Blood pudding", "category": "thịt_lợn"}
    wine = {"name_vi": "Rượu vang", "canonical_name_en": "Wine", "category": "nước giải khát"}
    soy_milk = {"name_vi": "Sữa đậu nành", "canonical_name_en": "Soy milk", "category": "hạt_các_loại"}
    peanut_butter = {"name_vi": "Bơ đậu phộng", "canonical_name_en": "Peanut butter", "category": "hạt_các_loại"}
    grasshopper = {"name_vi": "Châu chấu rang", "canonical_name_en": "Fried grasshopper", "category": "côn_trùng"}
    quail_egg = {"name_vi": "Trứng chim cút luộc", "canonical_name_en": "Boiled quail egg", "category": "trứng"}
    quail_meat = {"name_vi": "Chim cút quay", "canonical_name_en": "Roasted quail", "category": "thịt_gia_cầm"}

    assert violates_dietary_restrictions(fish_cake, ["vegetarian"]) is True
    assert violates_dietary_restrictions(fish_sauce, ["vegetarian"]) is True
    assert violates_dietary_restrictions(cheese, ["vegetarian"]) is False
    assert violates_dietary_restrictions(cheese, ["vegan"]) is True
    assert violates_dietary_restrictions(pork_sausage, ["halal"]) is True
    assert violates_dietary_restrictions(pate, ["halal"]) is True
    assert violates_dietary_restrictions(blood, ["halal"]) is True
    assert violates_dietary_restrictions(wine, ["halal"]) is True
    assert violates_dietary_restrictions(soy_milk, ["vegan"]) is False
    assert violates_dietary_restrictions(peanut_butter, ["vegan"]) is False
    assert violates_dietary_restrictions(grasshopper, ["vegetarian"]) is True
    assert violates_dietary_restrictions(grasshopper, ["vegan"]) is True
    assert violates_dietary_restrictions(quail_egg, ["vegetarian"]) is False
    assert violates_dietary_restrictions(quail_egg, ["vegan"]) is True
    assert violates_dietary_restrictions(quail_meat, ["vegetarian"]) is True


def test_plant_protein_classification_for_vegetarian_csp():
    from csp.classification import classify_food, get_dynamic_tags

    tofu = {"name_vi": "Đậu phụ luộc", "canonical_name_en": "Boiled tofu", "category": "hạt_các_loại", "protein": 10.9, "fat": 5.4, "carbs": 0.7}
    soy = {"name_vi": "Đậu tương, đậu nành luộc", "canonical_name_en": "Boiled soybean", "category": "hạt_các_loại", "protein": 16.6, "fat": 9.0, "carbs": 9.9}
    sweet_bean = {"name_vi": "Chè đậu đỏ ngọt", "canonical_name_en": "Sweet red bean soup", "category": "đồ_ăn_vặt", "protein": 4.0, "fat": 1.0, "carbs": 30.0}
    soy_milk = {"name_vi": "Sữa đậu nành", "canonical_name_en": "Soy milk", "category": "hạt_các_loại", "calories": 54, "protein": 3.0, "fat": 1.8, "carbs": 5.0}
    peanut_butter = {"name_vi": "Bơ đậu phộng", "canonical_name_en": "Peanut butter", "category": "hạt_các_loại", "calories": 588, "protein": 25.0, "fat": 50.0, "carbs": 20.0}

    assert "role_plant_protein" in get_dynamic_tags(tofu)
    assert classify_food(tofu) == "PLANT_PROTEIN"
    assert classify_food(soy) == "PLANT_PROTEIN"
    assert classify_food(sweet_bean) != "PLANT_PROTEIN"
    assert classify_food(soy_milk) != "PLANT_PROTEIN"
    assert classify_food(peanut_butter) != "PLANT_PROTEIN"


def test_plant_protein_only_becomes_core_for_vegetarian_profiles():
    foods = [
        {"food_id": 1, "canonical_name_en": "Chicken Breast", "name_vi": "Ức gà", "calories": 165, "protein": 31, "fat": 3.6, "carbs": 0, "cost_vnd_100g": 15000, "category": "thịt_gia_cầm"},
        {"food_id": 2, "canonical_name_en": "Boiled tofu", "name_vi": "Đậu phụ luộc", "calories": 76, "protein": 10.9, "fat": 5.4, "carbs": 0.7, "cost_vnd_100g": 6000, "category": "hạt_các_loại"},
        {"food_id": 3, "canonical_name_en": "White Rice", "name_vi": "Cơm trắng", "calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28, "cost_vnd_100g": 1800, "category": "tinh_bột"},
        {"food_id": 4, "canonical_name_en": "Cabbage", "name_vi": "Rau cải", "calories": 25, "protein": 1.3, "fat": 0.1, "carbs": 5.8, "cost_vnd_100g": 1500, "category": "rau_xanh"},
    ]
    constraints = NutrientConstraints(daily_calorie_target=1800.0)

    normal_scheduler = MealScheduler({"dietary_restrictions": []}, available_foods=foods, db_url="")
    normal_context = normal_scheduler._build_domain_context(foods, constraints, {})
    assert 1 in normal_context["lunch_ids"]
    assert 2 not in normal_context["lunch_ids"]

    vegetarian_scheduler = MealScheduler({"dietary_restrictions": ["vegetarian"]}, available_foods=foods, db_url="")
    vegetarian_context = vegetarian_scheduler._build_domain_context(foods, constraints, {})
    assert 2 in vegetarian_context["lunch_ids"]
    assert 2 in vegetarian_context["dinner_ids"]


def test_plant_based_repeat_limits_for_tofu_and_quail_eggs():
    foods = [
        {"food_id": 1, "canonical_name_en": "Grilled tofu", "name_vi": "Đậu phụ nướng", "calories": 120, "protein": 12, "fat": 7, "carbs": 2, "cost_vnd_100g": 6000, "category": "hạt_các_loại"},
        {"food_id": 2, "canonical_name_en": "Quail egg", "name_vi": "Trứng chim cút luộc", "calories": 158, "protein": 13, "fat": 11, "carbs": 1, "cost_vnd_100g": 9000, "category": "trứng"},
        {"food_id": 3, "canonical_name_en": "Chicken egg", "name_vi": "Trứng gà ta", "calories": 155, "protein": 13, "fat": 11, "carbs": 1, "cost_vnd_100g": 6000, "category": "trứng"},
    ]
    scheduler = MealScheduler(
        {"daily_calorie_target": 2300, "dietary_restrictions": ["vegetarian"], "plant_protein_as_core": True},
        available_foods=foods,
        db_url="",
    )
    constraints = NutrientConstraints(daily_calorie_target=2300.0)

    assert scheduler._max_occurrences_for_food(1, constraints, plant_restricted=True) == 4
    assert scheduler._max_occurrences_for_food(2, constraints, plant_restricted=True) == 1
    assert scheduler._max_occurrences_for_food(3, constraints, plant_restricted=True) == 2
    assert scheduler._food_prune_score(foods[1], "protein", constraints, {}, {}) > scheduler._food_prune_score(foods[2], "protein", constraints, {}, {})


def test_high_calorie_vegan_plan_remains_feasible_with_limited_plant_proteins():
    random.seed(42)
    foods = [
        {"food_id": 1, "canonical_name_en": "White Rice", "name_vi": "cơm trắng", "calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28, "cost_vnd_100g": 1800, "category": "tinh_bột"},
        {"food_id": 2, "canonical_name_en": "Bread", "name_vi": "bánh mì", "calories": 265, "protein": 9, "fat": 3.2, "carbs": 49, "cost_vnd_100g": 5000, "category": "tinh_bột"},
        {"food_id": 3, "canonical_name_en": "Oats", "name_vi": "yến mạch", "calories": 389, "protein": 16.9, "fat": 6.9, "carbs": 66.3, "cost_vnd_100g": 10000, "category": "tinh_bột"},
        {"food_id": 4, "canonical_name_en": "Tofu", "name_vi": "đậu phụ luộc", "calories": 76, "protein": 8, "fat": 4.8, "carbs": 1.9, "cost_vnd_100g": 5000, "category": "hạt_các_loại"},
        {"food_id": 5, "canonical_name_en": "Soybean", "name_vi": "đậu nành luộc", "calories": 173, "protein": 16.6, "fat": 9, "carbs": 9.9, "cost_vnd_100g": 6000, "category": "hạt_các_loại"},
        {"food_id": 6, "canonical_name_en": "Tempeh", "name_vi": "tempeh", "calories": 193, "protein": 19, "fat": 11, "carbs": 9, "cost_vnd_100g": 12000, "category": "hạt_các_loại"},
        {"food_id": 7, "canonical_name_en": "Spinach", "name_vi": "rau bó xôi", "calories": 23, "protein": 2.9, "fat": 0.4, "carbs": 3.6, "cost_vnd_100g": 4000, "category": "rau_xanh"},
        {"food_id": 8, "canonical_name_en": "Broccoli", "name_vi": "súp lơ xanh", "calories": 34, "protein": 2.8, "fat": 0.4, "carbs": 7, "cost_vnd_100g": 5000, "category": "rau_xanh"},
        {"food_id": 9, "canonical_name_en": "Banana", "name_vi": "chuối", "calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 22.8, "cost_vnd_100g": 2000, "category": "trái_cây"},
        {"food_id": 10, "canonical_name_en": "Dried jackfruit", "name_vi": "mít khô", "calories": 280, "protein": 2, "fat": 1, "carbs": 70, "cost_vnd_100g": 35000, "category": "đồ_ăn_vặt"},
    ]
    user = {
        "daily_calorie_target": 2300,
        "macro_ratios": {"protein": 0.22, "fat": 0.28, "carbs": 0.50},
        "budget_vnd_max": 200000,
        "exclude_snacks": True,
        "dietary_restrictions": ["vegan"],
        "plant_protein_as_core": True,
        "csp_time_budget_seconds": 7,
        "calorie_tolerance_pct": 0.18,
        "macro_tolerance_pct": 0.22,
        "diversity_penalty_weight": 0.35,
    }

    scheduler = MealScheduler(user, available_foods=foods, db_url="")
    result = scheduler.solve_with_relaxation(max_attempts=4)

    assert result["feasible"] is True
    assert len(result["meal_plan"]) == 7
    assert all(any(meal["meal_type"] == "snack" for meal in day["meals"]) for day in result["meal_plan"])


def test_high_calorie_plant_based_snack_can_have_multiple_items():
    random.seed(42)
    foods = [
        {"food_id": 1, "canonical_name_en": "Bread", "name_vi": "bánh mì", "calories": 265, "protein": 9, "fat": 3.2, "carbs": 49, "cost_vnd_100g": 5000, "category": "tinh_bột"},
        {"food_id": 2, "canonical_name_en": "Rice", "name_vi": "cơm trắng", "calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28, "cost_vnd_100g": 1800, "category": "tinh_bột"},
        {"food_id": 3, "canonical_name_en": "Tofu", "name_vi": "đậu phụ luộc", "calories": 76, "protein": 8, "fat": 4.8, "carbs": 1.9, "cost_vnd_100g": 5000, "category": "hạt_các_loại"},
        {"food_id": 4, "canonical_name_en": "Spinach", "name_vi": "rau bó xôi", "calories": 23, "protein": 2.9, "fat": 0.4, "carbs": 3.6, "cost_vnd_100g": 4000, "category": "rau_xanh"},
        {"food_id": 5, "canonical_name_en": "Banana", "name_vi": "chuối", "calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 22.8, "cost_vnd_100g": 2000, "category": "trái_cây"},
        {"food_id": 6, "canonical_name_en": "Peanuts", "name_vi": "lạc rang", "calories": 567, "protein": 25.8, "fat": 49.2, "carbs": 16.1, "cost_vnd_100g": 9000, "category": "hạt_các_loại"},
    ]
    user = {
        "daily_calorie_target": 2500,
        "macro_ratios": {"protein": 0.22, "fat": 0.28, "carbs": 0.50},
        "budget_vnd_max": 200000,
        "exclude_snacks": True,
        "dietary_restrictions": ["vegan"],
        "plant_protein_as_core": True,
    }
    scheduler = MealScheduler(user_profile=user, available_foods=foods, db_url="")
    constraints = NutrientConstraints(
        daily_calorie_target=2500.0,
        macro_ratios=user["macro_ratios"],
        budget_vnd_max=user["budget_vnd_max"],
    )

    day_meals = scheduler._get_meal_plan_for_solution(
        {"breakfast": 1, "lunch": 3, "dinner": 3, "snack": 5},
        constraints,
        1.0,
        all_carbs=[foods[1]],
        all_proteins=[foods[2]],
        all_fibers=[foods[3]],
        all_snacks=[foods[4], foods[5]],
        day_excluded_ids=None,
    )

    snack = next(meal for meal in day_meals if meal["meal_type"] == "snack")
    assert len(snack["components"]) == 2
    assert {component["food_id"] for component in snack["components"]} == {5, 6}


def test_che_exclusion_and_suffix_stripping():
    from csp.scheduler import get_dynamic_tags, MealScheduler
    from csp.constraints import NutrientConstraints
    
    # 1. Chè exclusion from role_carb
    che_food = {"name_vi": "Chè đậu đỏ ngọt", "canonical_name_en": "Sweet red bean soup", "category": "đồ_ăn_vặt"}
    tags = get_dynamic_tags(che_food)
    assert "role_carb" not in tags
    
    # 2. Suffix stripping check in scheduler helper
    user = {
        "daily_calorie_target": 2200,
        "macro_ratios": {"protein": 0.30, "fat": 0.30, "carbs": 0.40},
        "budget_vnd_max": 200000,
        "exclude_snacks": True,
    }
    mock_foods = [
        {"food_id": 1, "canonical_name_en": "Chicken Breast", "name_vi": "Ức gà nguyên chất", "calories": 165, "protein": 31, "fat": 3.6, "carbs": 0, "cost_vnd_100g": 15000, "category": "thịt_gia_cầm"},
        {"food_id": 2, "canonical_name_en": "White Rice", "name_vi": "Cơm trắng", "calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28, "cost_vnd_100g": 1800, "category": "tinh_bột"},
        {"food_id": 3, "canonical_name_en": "Cabbage", "name_vi": "Rau cải khô", "calories": 25, "protein": 1.3, "fat": 0.1, "carbs": 5.8, "cost_vnd_100g": 1500, "category": "rau_xanh"},
    ]
    scheduler = MealScheduler(user_profile=user, available_foods=mock_foods, db_url="")
    
    sol = {"breakfast": 1, "lunch": 1, "dinner": 1}
    all_carbs = [mock_foods[1]]
    all_proteins = [mock_foods[0]]
    all_fibers = [mock_foods[2]]
    
    constraints = NutrientConstraints(
        daily_calorie_target=2200.0,
        macro_ratios={"protein": 0.30, "fat": 0.30, "carbs": 0.40},
    )
    
    day_meals = scheduler._get_meal_plan_for_solution(
        sol, constraints, 1.0,
        all_carbs, all_proteins, all_fibers, [], day_excluded_ids=None
    )
    
    # Check that "nguyên chất" and "khô" are stripped
    breakfast_name = day_meals[0]["name"]
    lunch_name = day_meals[1]["name"]
    assert "nguyên chất" not in breakfast_name.lower()
    assert "khô" not in lunch_name.lower()
    assert "Ức gà" in breakfast_name
    assert "Rau cải" in lunch_name
