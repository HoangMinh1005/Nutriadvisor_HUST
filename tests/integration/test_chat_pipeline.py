import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

def test_chat_out_of_scope_guardrails():
    """Verify that an out-of-scope query is correctly rejected with Format 2 structure."""
    payload = {
        "message": "Thời tiết hôm nay ở Hà Nội thế nào?"
    }
    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "rejected"
    assert data["intent"] == "OUT_OF_SCOPE"
    assert "NutriAdvisor hiện tại chỉ hỗ trợ" in data["reply"]

def test_chat_query_nutrition_success():
    """Verify that a valid QUERY_NUTRITION query yields correct database food parameters."""
    payload = {
        "message": "Hàm lượng protein và calo trong ức gà là bao nhiêu?"
    }
    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "success"
    assert data["intent"] == "QUERY_NUTRITION"
    assert data["found"] is True
    assert isinstance(data["foods"], list)
    assert len(data["foods"]) > 0
    # Any returned food should contain "gà"
    assert any("gà" in f["name_vi"].lower() for f in data["foods"])
    assert data["foods"][0]["calories"] > 0
    assert data["foods"][0]["protein"] > 0

def test_chat_find_alternative_success():
    """Verify that a valid FIND_ALTERNATIVE query routes to KNN matching results."""
    payload = {
        "message": "Tôi muốn thay cơm trắng bằng gì để tăng chất xơ?"
    }
    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "success"
    assert data["intent"] == "FIND_ALTERNATIVE"
    assert data["found"] is True
    assert any(k in data["target_food"]["name_vi"].lower() for k in ["cơm", "rice"])
    assert isinstance(data["replacements"], list)
    assert len(data["replacements"]) > 0
    # Each replacement should have match_score and food parameters
    for replacement in data["replacements"]:
        assert "food_id" in replacement
        assert "name_vi" in replacement
        assert "match_score" in replacement
        assert 0.0 <= replacement["match_score"] <= 1.0

def test_chat_suggest_meal_success():
    """Verify that a valid SUGGEST_MEAL query routes to a single-day CSP suggestion."""
    payload = {
        "message": "Gợi ý thực đơn 2000 calo nhiều đạm để tăng cơ",
        "user_profile": {
            "macro_ratios": {"protein": 0.35, "fat": 0.25, "carbs": 0.40}
        }
    }
    response = client.post("/api/v1/chat", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "success"
    assert data["intent"] == "SUGGEST_MEAL"
    assert data["feasible"] is True
    assert isinstance(data["meals"], list)
    assert len(data["meals"]) > 0
    
    # Assert calories and cost are populated and reasonable
    assert data["total_calories"] > 0
    assert data["total_cost"] > 0
