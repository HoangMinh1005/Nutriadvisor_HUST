import pytest
from fastapi.testclient import TestClient
import backend.app.main as main_module
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


def test_chat_suggest_meal_context_overrides_profile(monkeypatch):
    """Explicit chat context should beat stored profile defaults."""
    captured = {}

    class FakeIntentEngine:
        def predict_chat_intent(self, message):
            return {
                "status": "success",
                "intent": "SUGGEST_MEAL",
                "entities": {
                    "calories": 1800,
                    "budget_vnd": 120000,
                    "health_goal": "muscle_gain",
                    "allergies": [],
                    "dietary_restrictions": [],
                    "query_keyword": "giàu",
                    "nutrients": ["protein_g"],
                    "profile_updates": {
                        "daily_calorie_target": 1800,
                    },
                },
            }

    class FakeMealPipeline:
        def generate_meal_plan(self, profile):
            captured["profile"] = profile
            return {
                "feasible": True,
                "meal_plan": [{
                    "day": 1,
                    "meals": [{
                        "meal_type": "lunch",
                        "food_id": 1,
                        "name": "Trứng gà ta + cơm",
                        "calories": 600,
                        "protein": 35,
                        "fat": 15,
                        "carbs": 70,
                        "total_cost_vnd": 25000,
                    }],
                }],
            }

    monkeypatch.setattr(main_module, "intent_engine", FakeIntentEngine())
    monkeypatch.setattr(main_module, "meal_pipeline", FakeMealPipeline())

    payload = {
        "message": "Gợi ý thực đơn bình thường 1800 calo nhiều protein kinh phí 120k",
        "user_profile": {
            "daily_calorie_target": 2600,
            "budget_vnd_max": 300000,
            "dietary_restrictions": ["vegan"],
            "macro_ratios": {"protein": 0.20, "fat": 0.30, "carbs": 0.50},
        },
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["effective_profile"]["daily_calorie_target"] == 1800.0
    assert data["effective_profile"]["budget_vnd_max"] == 120000.0
    assert data["effective_profile"]["dietary_restrictions"] == []
    assert data["effective_profile"]["macro_ratios"]["protein"] >= 0.35
    assert captured["profile"]["daily_calorie_target"] == 1800.0
    assert captured["profile"]["dietary_restrictions"] == []


def test_chat_suggest_meal_uses_isolated_defaults_when_context_omits_fields(monkeypatch):
    """Saved profile restrictions must not leak into one-off chat meal requests."""
    captured = {}

    class FakeIntentEngine:
        def predict_chat_intent(self, message):
            return {
                "status": "success",
                "intent": "SUGGEST_MEAL",
                "entities": {
                    "calories": 3000,
                    "allergies": ["hải sản"],
                    "dietary_restrictions": [],
                    "profile_updates": {
                        "daily_calorie_target": 3000,
                    },
                },
            }

    class FakeMealPipeline:
        def generate_meal_plan(self, profile):
            captured["profile"] = profile
            return {
                "feasible": True,
                "meal_plan": [{
                    "day": 1,
                    "meals": [{
                        "meal_type": "lunch",
                        "food_id": 1,
                        "name": "Cơm + thịt bò + rau",
                        "calories": 850,
                        "protein": 45,
                        "fat": 20,
                        "carbs": 100,
                        "total_cost_vnd": 45000,
                    }],
                }],
            }

    monkeypatch.setattr(main_module, "intent_engine", FakeIntentEngine())
    monkeypatch.setattr(main_module, "meal_pipeline", FakeMealPipeline())

    payload = {
        "message": "Gợi ý thực đơn 3000 calo cho người dị ứng hải sản",
        "user_profile": {
            "daily_calorie_target": 1800,
            "budget_vnd_max": 50000,
            "allergies": ["trứng"],
            "dietary_restrictions": ["vegan"],
            "physical_activity_level": "Sedentary",
            "macro_ratios": {"protein": 0.15, "fat": 0.30, "carbs": 0.55},
        },
    }
    response = client.post("/api/v1/chat", json=payload)

    assert response.status_code == 200
    data = response.json()
    effective_profile = data["effective_profile"]
    assert effective_profile["daily_calorie_target"] == 3000.0
    assert effective_profile["budget_vnd_max"] == 200000.0
    assert effective_profile["allergies"] == ["hải sản"]
    assert effective_profile["dietary_restrictions"] == []
    assert effective_profile["physical_activity_level"] == "Moderately Active"
    assert captured["profile"]["budget_vnd_max"] == 200000.0
    assert captured["profile"]["dietary_restrictions"] == []
    assert captured["profile"]["allergies"] == ["hải sản"]
