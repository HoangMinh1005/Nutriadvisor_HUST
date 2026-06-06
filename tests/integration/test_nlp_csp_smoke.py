"""Smoke integration tests linking NLP payload to a mock CSP checker."""

from __future__ import annotations

import json
from backend.ml.nlp import IntentCache, IntentEngine, load_default_training_examples


def stub_csp_validation(payload: dict) -> list[str]:
    """Mock CSP logic to validate that the NLP payload respects the spec."""
    errors = []

    if "user" not in payload:
        errors.append("Missing 'user' field.")
    if "goal" not in payload or "type" not in payload["goal"]:
        errors.append("Missing 'goal.type'.")
    
    constraints = payload.get("constraints", {})
    if not isinstance(constraints.get("exclude"), list):
        errors.append("'constraints.exclude' must be a list.")
    if "budget_vnd_max" in constraints and not isinstance(constraints["budget_vnd_max"], int):
        errors.append("'constraints.budget_vnd_max' must be an integer.")

    variables = payload.get("variables", {})
    if "candidates" not in variables or not isinstance(variables["candidates"], list):
        errors.append("'variables.candidates' must be a list.")
    
    objectives = payload.get("objectives", {})
    if "maximize" not in objectives or "minimize" not in objectives:
        errors.append("Missing maximize/minimize in 'objectives'.")

    return errors


def test_nlp_to_csp_smoke(tmp_path):
    # Setup mock mapping
    mapping = {"cơm trắng": "food_004", "ức gà": "food_001", "vịt": "food_010"}
    mapping_path = tmp_path / "food_mapping.json"
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")

    # Initialize Engine
    engine = IntentEngine(model_dir=tmp_path / "nlp-model", cache=IntentCache(), food_mapping=str(mapping_path), gemini_api_key="")
    engine.train(load_default_training_examples())

    # 1. Query: Replacement with objectives
    res_1 = engine.predict("Tôi muốn thay cơm trắng bằng gì để tăng protein và giảm mỡ")
    payload_1 = engine.to_csp_payload(res_1)
    
    # 2. Query: Budget recommendation with allergy
    res_2 = engine.predict("thực đơn giảm cân 80k một ngày không có hải sản")
    payload_2 = engine.to_csp_payload(res_2)

    # Validate payloads using stub CSP logic
    err_1 = stub_csp_validation(payload_1)
    err_2 = stub_csp_validation(payload_2)

    assert not err_1, f"CSP Validation failed for Query 1: {err_1}"
    assert not err_2, f"CSP Validation failed for Query 2: {err_2}"

    # Specific checks mapped to NLP extraction logic
    assert payload_1["meta"]["query_keyword"] == "thay thế"
    assert payload_1["constraints"]["replacement_target"] == "cơm trắng"
    assert any(c.get("id") == "food_004" for c in payload_1["variables"]["candidates"])
    assert "protein_g" in payload_1["objectives"]["maximize"]

    assert payload_2["constraints"]["budget_vnd_max"] == 80000
    assert "hải sản" in payload_2["constraints"]["exclude"]
    assert payload_2["goal"]["type"] in ["recommend_meal", "update_profile"]
