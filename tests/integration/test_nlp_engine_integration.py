"""Integration test for the NLP engine package."""

from __future__ import annotations

from backend.ml.nlp import IntentCache, IntentEngine, load_default_training_examples


def test_nlp_engine_can_train_save_and_reload(tmp_path):
    model_dir = tmp_path / "model"
    cache = IntentCache()

    engine = IntentEngine(model_dir=model_dir, cache=cache)
    stats = engine.train(load_default_training_examples())
    assert stats["samples"] >= 20

    first = engine.predict("Tôi muốn thực đơn 2500 calo để tăng cơ, không có hải sản")
    assert first.intent == "recommend_meal"

    reloaded = IntentEngine(model_dir=model_dir, cache=cache)
    second = reloaded.predict("Tôi muốn thực đơn 2500 calo để tăng cơ, không có hải sản")
    assert second.intent == first.intent
    assert second.entities["calories"] == 2500
