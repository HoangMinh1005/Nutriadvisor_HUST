from backend.app.services.health_forecaster import HealthForecaster


def _fake_forecaster():
    forecaster = HealthForecaster.__new__(HealthForecaster)
    forecaster.activity_mapping = {
        "Sedentary": 0,
        "Lightly Active": 1,
        "Moderately Active": 2,
        "Very Active": 3,
    }
    forecaster.sleep_mapping = {
        "Poor": 0,
        "Fair": 1,
        "Good": 2,
        "Excellent": 3,
    }
    forecaster._predict_change_kg = lambda input_dict: (
        float(input_dict["Daily Caloric Surplus/Deficit"]) / 1000.0
        + float(input_dict["Stress Level"]) * 0.005
        + float(input_dict["Sleep_encoded"]) * 0.002
    )
    forecaster._global_feature_importance = lambda: {}
    return forecaster


def test_activity_importance_recomputes_surplus_from_maintenance_anchor():
    forecaster = _fake_forecaster()

    current_surplus = -464.0
    next_surplus = forecaster._surplus_for_activity(
        calories=2200.0,
        current_surplus=current_surplus,
        current_activity="Moderately Active",
        next_activity="Very Active",
    )

    assert next_surplus < current_surplus


def test_personalized_importance_reflects_activity_via_recomputed_surplus():
    forecaster = _fake_forecaster()

    importance = forecaster._personalized_feature_importance(
        calories=2200.0,
        surplus=-464.0,
        gender_encoded=1.0,
        activity="Moderately Active",
        activity_encoded=2.0,
        sleep="Good",
        sleep_encoded=2.0,
        stress=5.0,
    )

    assert importance["Physical Activity Level"] > 0.05
