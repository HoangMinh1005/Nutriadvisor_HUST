import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_login_new_user():
    """Verify that logging in with a non-existent email redirects to onboarding."""
    payload = {
        "email": "nonexistent.student@sis.hust.edu.vn",
        "password": "password123"
    }
    response = client.post("/api/v1/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "new_user"


def test_profile_creation_and_recalc_flow():
    """Verify that posting to /api/v1/profile saves the profile, runs CSP (3 meals), and ML forecast."""
    email = "test.minh@sis.hust.edu.vn"
    profile_payload = {
        "full_name": "Vũ Hoàng Minh Test",
        "email": email,
        "gender": "male",
        "age": 21,
        "height_cm": 175.0,
        "weight_kg": 72.5,
        "daily_calorie_target": 2200,
        "budget_vnd_max": 200000,
        "physical_activity_level": "Moderately Active",
        "sleep_quality": "Good",
        "stress_level": 6,
        "allergies": [],
        "weight_goal": "maintain"
    }
    
    response = client.post("/api/v1/profile", json=profile_payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "success"
    assert data["profile"]["email"] == email
    assert data["profile"]["full_name"] == "Vũ Hoàng Minh Test"
    assert data["profile"]["daily_calorie_target"] == 2200
    assert data["profile"]["budget_vnd_max"] == 200000
    
    # Verify the generated 7-day meal plan
    assert "meal_plan" in data
    assert len(data["meal_plan"]) == 7
    for day in data["meal_plan"]:
        # Verify exactly 3 slots per day (breakfast, lunch, dinner)
        assert len(day["meals"]) == 3
        slots = [m["meal_type"] for m in day["meals"]]
        assert "breakfast" in slots
        assert "lunch" in slots
        assert "dinner" in slots
        assert "snack" not in slots  # No snacks allowed as per 3-meal requirement
        
    # Verify forecasting trend
    assert "forecast" in data
    assert "forecast_chart_data" in data["forecast"]
    assert "feature_importance" in data["forecast"]


def test_login_existing_user():
    """Verify that logging in with an existing email returns profile, plan, and forecast."""
    payload = {
        "email": "test.minh@sis.hust.edu.vn",
        "password": "password123"
    }
    response = client.post("/api/v1/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "success"
    assert data["profile"]["email"] == "test.minh@sis.hust.edu.vn"
    assert len(data["meal_plan"]) == 7
    assert "forecast" in data


def test_food_alternatives_endpoint():
    """Verify that GET /api/v1/food/{food_id}/alternatives returns 5 similar alternatives."""
    # Food ID 1 is chicken breast (ức gà)
    response = client.get("/api/v1/food/1/alternatives?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "food_id" in data[0]
    assert "name_vi" in data[0]
    assert "match_score" in data[0]


def test_meal_plan_swap():
    """Verify that swapping a food in the weekly schedule updates database successfully."""
    # First, let's login or profile to get dates
    login_res = client.post("/api/v1/login", json={"email": "test.minh@sis.hust.edu.vn"})
    login_data = login_res.json()
    plan_date = login_data["meal_plan"][0]["date"]
    original_food_id = login_data["meal_plan"][0]["meals"][0]["food_id"]
    
    # Retrieve alternatives for original_food_id
    alt_res = client.get(f"/api/v1/food/{original_food_id}/alternatives?limit=1")
    alt_data = alt_res.json()
    replacement_food_id = alt_data[0]["food_id"]
    
    swap_payload = {
        "email": "test.minh@sis.hust.edu.vn",
        "plan_date": plan_date,
        "meal_slot_code": "breakfast",
        "original_food_id": original_food_id,
        "replacement_food_id": replacement_food_id
    }
    
    response = client.post("/api/v1/meal-plan/swap", json=swap_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    
    # Query login again to confirm the food was indeed swapped
    login_res_2 = client.post("/api/v1/login", json={"email": "test.minh@sis.hust.edu.vn"})
    login_data_2 = login_res_2.json()
    new_food_id = login_data_2["meal_plan"][0]["meals"][0]["food_id"]
    assert new_food_id == replacement_food_id


def test_serve_frontend_index():
    """Verify that GET / returns index.html successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"<!DOCTYPE html>" in response.content
    assert b"NutriAdvisor_HUST" in response.content


def test_serve_frontend_assets():
    """Verify that GET /assets/... static files can be retrieved."""
    response = client.get("/assets/css/styles.css")
    assert response.status_code == 200
    assert b"body" in response.content or b"html" in response.content or b":root" in response.content
