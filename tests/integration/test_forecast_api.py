import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_forecast_api_success():
    """Verify that a valid payload returns the telemetry data correctly."""
    payload = {
        "current_weight_kg": 70.0,
        "height_cm": 175.0,
        "gender": "M",
        "physical_activity_level": "Moderately Active",
        "daily_calories_consumed": 2500.0,
        "daily_caloric_surplus": 500.0,
        "sleep_quality": "Good",
        "stress_level": 5.0
    }
    response = client.post("/api/v1/forecast", json=payload)
    assert response.status_code == 200, f"Error: {response.text}"
    
    data = response.json()
    assert data["status"] == "success"
    assert data["current_weight"] == 70.0
    assert data["weight_unit"] == "kg"
    
    # Check 5-week trajectory data (W0 to W4)
    chart_data = data["forecast_chart_data"]
    assert isinstance(chart_data, list)
    assert len(chart_data) == 5
    
    # W0 (Hiện tại)
    assert chart_data[0]["timeline"] == "Hiện tại"
    assert chart_data[0]["predicted_weight"] == 70.0
    assert "predicted_bmi" in chart_data[0]
    
    # W1 - W4
    for i in range(1, 5):
        assert chart_data[i]["timeline"] == f"Tuần {i}"
        assert "predicted_weight" in chart_data[i]
        assert "predicted_bmi" in chart_data[i]
        
    # Check feature importance telemetry
    importance = data["feature_importance"]
    assert isinstance(importance, dict)
    for key in ["Stress Level", "Caloric Surplus/Deficit", "Sleep Quality", "Physical Activity Level"]:
        assert key in importance

def test_forecast_api_validation_error():
    """Verify that invalid inputs are correctly rejected with 422."""
    # Scenario 1: Missing required field (gender)
    payload = {
        "current_weight_kg": 70.0,
        "height_cm": 175.0,
        "physical_activity_level": "Moderately Active",
        "daily_calories_consumed": 2500.0,
        "daily_caloric_surplus": 500.0,
        "sleep_quality": "Good",
        "stress_level": 5.0
    }
    response = client.post("/api/v1/forecast", json=payload)
    assert response.status_code == 422

    # Scenario 2: Out of bound stress_level (11.0 > 10)
    payload = {
        "current_weight_kg": 70.0,
        "height_cm": 175.0,
        "gender": "M",
        "physical_activity_level": "Moderately Active",
        "daily_calories_consumed": 2500.0,
        "daily_caloric_surplus": 500.0,
        "sleep_quality": "Good",
        "stress_level": 11.0
    }
    response = client.post("/api/v1/forecast", json=payload)
    assert response.status_code == 422
