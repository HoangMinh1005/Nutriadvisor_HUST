"""Unit tests for the NLP engine."""

from __future__ import annotations

import threading
import time

from backend.ml.nlp import IntentCache, IntentEngine, NLPResult, load_default_training_examples
import json


def _trained_engine(tmp_path, *, use_gemini: bool = False):
    engine = IntentEngine(
        model_dir=tmp_path / "nlp-model",
        cache=IntentCache(),
        gemini_api_key="test-key" if use_gemini else "",
    )
    engine.train(load_default_training_examples())
    return engine


def test_load_default_training_examples_has_data():
    examples = load_default_training_examples()
    assert len(examples) >= 20
    assert {example.intent for example in examples} >= {"recommend_meal", "update_profile", "ask_nutrition"}


def test_local_prediction_and_entity_extraction(tmp_path):
    engine = _trained_engine(tmp_path)

    query = "Tôi muốn thực đơn 100k mỗi ngày để tăng cơ, không có hải sản"
    result = engine.predict(query)

    assert isinstance(result, NLPResult)
    assert result.intent == "recommend_meal"
    assert result.confidence > 0.3
    assert result.entities["budget_vnd"] == 100000
    assert result.entities["health_goal"] == "muscle_gain"
    assert "hải sản" in result.entities["allergies"]


def test_update_profile_query(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("Tôi muốn giảm 3kg trong 2 tháng")

    assert result.intent == "update_profile"
    assert result.entities["weight_change_kg"] == -3.0
    assert result.entities["duration_days"] == 60
    assert result.entities["health_goal"] == "weight_loss"


def test_duration_words_are_parsed(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("Tôi muốn giảm 5 cân trong một tháng")

    assert result.entities["weight_change_kg"] == -5.0
    assert result.entities["duration_days"] == 30
    assert result.entities["health_goal"] == "weight_loss"


def test_weight_loss_with_gym_keyword_keeps_negative_weight_change(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("Tôi là nữ 20 tuổi, bị dị ứng với lạc và hải sản, muốn gợi ý thực đơn cho người tập gym muốn giảm 5 cân với kinh phí 200k một ngày")

    assert result.intent == "recommend_meal"
    assert result.entities["weight_change_kg"] == -5.0
    assert result.entities["health_goal"] == "weight_loss"


def test_budget_prefers_explicit_budget_cue_over_age(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict(
        "tôi là nữ 20 tuổi, bị dị ứng với lac và hải sản muốn gợi ý thc đơn khảng 1800 calo cho người tập gym muốn giảm 5 cân trong một tháng với kinh phí 200k một ng"
    )

    assert result.entities["budget_vnd"] == 200000
    assert result.entities["calories"] == 1800
    assert result.entities["weight_change_kg"] == -5.0
    assert result.entities["duration_days"] == 30
    assert "ca" not in result.entities["allergies"]
    assert "lac" in result.entities["allergies"]
    assert "hải sản" in result.entities["allergies"]
    assert result.entities["query_keyword"] == "budget_conscious"


def test_meal_suggestion_with_heavy_activity_typo_routes_to_suggest_meal(tmp_path):
    engine = _trained_engine(tmp_path)

    query = "gợi ý thực đơn cho người vận dộng nặng 2500 calo một ngày, chi phí 200k"
    result = engine.predict(query)
    chat_result = engine.predict_chat_intent(query)

    assert result.entities["calories"] == 2500
    assert result.entities["budget_vnd"] == 200000
    assert result.entities["profile_updates"]["physical_activity_level"] == "Very Active"
    assert chat_result["status"] == "success"
    assert chat_result["intent"] == "SUGGEST_MEAL"


def test_profile_updates_are_extracted(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("Tôi là nữ, sinh năm 1998, cao 165cm, nặng 58kg và muốn ăn 1800 kcal mỗi ngày")

    profile_updates = result.entities["profile_updates"]
    assert profile_updates["gender"] == "female"
    assert profile_updates["birth_year"] == 1998
    assert profile_updates["height_cm"] == 165.0
    assert profile_updates["weight_kg"] == 58.0
    assert profile_updates["daily_calorie_target"] == 1800


def test_replacement_target_and_query_keyword_are_extracted(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("Tôi muốn thay cơm trắng bằng gì để tăng protein và chất xơ")

    assert result.entities["query_keyword"] == "thay thế"
    assert result.entities["replacement_target"] == "cơm trắng"
    assert "cơm trắng" in result.entities["food_items"]
    assert "protein_g" in result.entities["nutrients"]


def test_nutrient_focus_query_extracts_nutrients(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("gợi ý thực phẩm giàu protein")

    assert result.intent == "recommend_meal"
    assert result.entities["query_keyword"] == "giàu"
    assert "protein_g" in result.entities["nutrients"]
    assert result.entities["replacement_target"] is None


def test_nutrition_value_question_maps_to_ask_nutrition(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("Lượng protein trong thịt bò")

    assert result.intent == "ask_nutrition"
    assert result.entities["query_keyword"] == "bao nhiêu"
    assert "thịt bò" in result.entities["food_items"]
    assert "protein_g" in result.entities["nutrients"]
    assert result.entities["replacement_target"] is None


def test_nutrition_query(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("100g ức gà có bao nhiêu protein?")

    assert result.intent == "ask_nutrition"
    assert result.entities["health_goal"] == "unknown"
    assert result.entities["query_keyword"] == "bao nhiêu"
    assert "ức gà" in result.entities["food_items"]
    assert "protein_g" in result.entities["nutrients"]
    assert result.entities["replacement_target"] is None
    assert result.source == "local"


def test_cache_round_trip(tmp_path):
    cache = IntentCache()
    engine = IntentEngine(model_dir=tmp_path / "nlp-model", cache=cache)
    engine.train(load_default_training_examples())

    first = engine.predict("Tôi muốn thực đơn 100k mỗi ngày để tăng cơ, không có hải sản")
    second = engine.predict("Tôi muốn thực đơn 100k mỗi ngày để tăng cơ, không có hải sản")

    assert first.intent == second.intent
    assert second.source in {"local", "cache"}


def test_parse_json_payload_handles_code_fence(tmp_path):
    engine = _trained_engine(tmp_path)
    payload = engine._parse_json_payload(
        "```json\n{\n  \"intent\": \"recommend_meal\",\n  \"confidence\": 0.98,\n  \"entities\": {\"budget_vnd\": 100000, \"calories\": 2500, \"health_goal\": \"muscle_gain\", \"allergies\": [\"hải sản\"], \"dietary_restrictions\": [], \"weight_change_kg\": null, \"duration_days\": null}\n}\n```"
    )

    assert payload is not None
    result = engine._normalize_result(payload, source="gemini", raw_response="demo")
    assert result.intent == "recommend_meal"
    assert result.entities["budget_vnd"] == 100000


def test_normalize_result_v2_entities(tmp_path):
    engine = _trained_engine(tmp_path)
    payload = {
        "intent": "recommend_meal",
        "confidence": 0.9,
        "entities": {
            "query_keyword": "giàu",
            "food_items": ["thịt bò"],
            "nutrients": ["protein_g", "protein_g"],
            "profile_updates": {"gender": "female"},
            "replacement_target": "com trang",
        },
    }

    result = engine._normalize_result(payload, source="gemini", raw_response="demo")
    assert result.entities["query_keyword"] == "giàu"
    assert result.entities["food_items"] == ["thịt bò"]
    assert result.entities["nutrients"] == ["protein_g"]
    assert result.entities["profile_updates"]["gender"] == "female"
    assert result.entities["replacement_target"] == "com trang"


def test_gemini_model_fallback_tries_next_model(tmp_path):
    engine = _trained_engine(tmp_path)
    engine.gemini_api_key = "fake-key"
    engine.gemini_model = "gemini-primary"
    engine.gemini_model_fallbacks = ["gemini-backup"]

    calls: list[str] = []

    def fake_predict_with_model(user_query: str, model_name: str):
        calls.append(model_name)
        if model_name == "gemini-primary":
            return None
        return NLPResult(
            intent="ask_nutrition",
            confidence=0.99,
            entities=engine._default_entities(),
            source="gemini",
            raw_response="{\"intent\":\"ask_nutrition\"}",
        )

    engine._predict_via_gemini_with_model = fake_predict_with_model  # type: ignore[method-assign]

    result = engine.predict("Lượng protein trong thịt bò")

    assert calls == ["gemini-primary", "gemini-backup"]
    assert result.intent == "ask_nutrition"
    assert result.source == "gemini"


def test_cache_ttl_for_intent_helper(tmp_path):
    engine = _trained_engine(tmp_path)

    assert engine._cache_ttl_for_intent("update_profile") == 7 * 24 * 60 * 60
    assert engine._cache_ttl_for_intent("ask_nutrition") == 3 * 24 * 60 * 60
    assert engine._cache_ttl_for_intent("recommend_meal") == 12 * 60 * 60
    assert engine._cache_ttl_for_intent("unknown") == 15 * 60


def test_negative_cache_skips_gemini_after_429(tmp_path):
    engine = _trained_engine(tmp_path, use_gemini=True)
    calls = {"count": 0}

    def fake_predict_via_gemini(user_query: str):
        calls["count"] += 1
        engine._last_gemini_error_code = 429
        return None

    engine._predict_via_gemini = fake_predict_via_gemini  # type: ignore[method-assign]

    first = engine.predict("sdfsfsdfsdfds")
    second = engine.predict("sdfsfsdfsdfds")

    assert calls["count"] == 1
    assert first.intent == second.intent
    assert first.source == "local"


def test_singleflight_avoids_duplicate_gemini_calls(tmp_path):
    engine = _trained_engine(tmp_path, use_gemini=True)
    calls = {"count": 0}
    gemini_started = threading.Event()
    release_gemini = threading.Event()

    def fake_predict_via_gemini(user_query: str):
        calls["count"] += 1
        gemini_started.set()
        release_gemini.wait(timeout=5)
        return NLPResult(
            intent="ask_nutrition",
            confidence=0.99,
            entities=engine._default_entities(),
            source="gemini",
            raw_response="{\"intent\":\"ask_nutrition\"}",
        )

    engine._predict_via_gemini = fake_predict_via_gemini  # type: ignore[method-assign]

    results: list[NLPResult] = []

    def worker() -> None:
        results.append(engine.predict("sdfsfsdfsdfds"))

    first_thread = threading.Thread(target=worker)
    second_thread = threading.Thread(target=worker)

    first_thread.start()
    assert gemini_started.wait(timeout=5)
    second_thread.start()
    time.sleep(0.1)
    release_gemini.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert calls["count"] == 1
    assert len(results) == 2
    assert all(result.intent == "ask_nutrition" for result in results)


def test_to_csp_payload_basic(tmp_path):
    engine = _trained_engine(tmp_path)

    result = engine.predict("Tôi muốn thay cơm trắng bằng gì để tăng protein và chất xơ")
    payload = engine.to_csp_payload(result)

    assert isinstance(payload, dict)
    assert "variables" in payload and "candidates" in payload["variables"]
    assert "objectives" in payload
    # Should prefer protein if detected
    assert "maximize" in payload["objectives"]
    assert any("protein" in s for s in payload["objectives"]["maximize"]) or payload["objectives"]["maximize"] == []


def test_food_mapping_integration(tmp_path):
    # create a sample mapping file
    mapping = {"cơm trắng": "food_004", "ức gà": "food_001"}
    mapping_path = tmp_path / "food_mapping.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")

    engine = IntentEngine(model_dir=tmp_path / "nlp-model", cache=IntentCache(), food_mapping=str(mapping_path))
    engine.train(load_default_training_examples())

    result = engine.predict("Tôi muốn thay cơm trắng bằng gì để tăng protein và chất xơ")
    payload = engine.to_csp_payload(result)

    assert isinstance(payload, dict)
    candidates = payload["variables"]["candidates"]
    assert isinstance(candidates, list)
    # expect structured candidates with id/name
    assert any(isinstance(c, dict) and c.get("id") == "food_004" for c in candidates)


def test_predict_chat_intent_guardrails(tmp_path):
    engine = _trained_engine(tmp_path)
    engine.cache.clear()

    # In-scope SUGGEST_MEAL
    suggest_res = engine.predict_chat_intent("Tôi nên ăn gì vào bữa trưa để tăng cơ?")
    assert suggest_res["status"] == "success"
    assert suggest_res["intent"] == "SUGGEST_MEAL"

    # In-scope QUERY_NUTRITION
    query_res = engine.predict_chat_intent("Lượng protein trong 100g ức gà là bao nhiêu?")
    assert query_res["status"] == "success"
    assert query_res["intent"] == "QUERY_NUTRITION"

    # In-scope FIND_ALTERNATIVE
    alt_res = engine.predict_chat_intent("Tôi muốn thay thế cơm trắng bằng gì để tăng chất xơ?")
    assert alt_res["status"] == "success"
    assert alt_res["intent"] == "FIND_ALTERNATIVE"

    # Out-of-scope (general update_profile in chat)
    out_profile = engine.predict_chat_intent("Tôi cao 1m8 và nặng 70kg")
    assert out_profile["status"] == "rejected"
    assert out_profile["intent"] == "OUT_OF_SCOPE"
    assert "NutriAdvisor hiện tại chỉ hỗ trợ" in out_profile["reply"]

    # Out-of-scope (completely random query)
    out_random = engine.predict_chat_intent("Thời tiết hôm nay ở Hà Nội thế nào?")
    assert out_random["status"] == "rejected"
    assert out_random["intent"] == "OUT_OF_SCOPE"
    assert "NutriAdvisor hiện tại chỉ hỗ trợ" in out_random["reply"]
