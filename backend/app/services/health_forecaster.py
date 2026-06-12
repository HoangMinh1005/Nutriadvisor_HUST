import os
import pickle
import pandas as pd
from typing import Any, Dict

# Resolve absolute path to models/health_predictor.pkl relative to this file
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
MODEL_PATH = os.path.join(BASE_DIR, "models", "health_predictor.pkl")
if not os.path.exists(MODEL_PATH) and os.path.exists("/models/health_predictor.pkl"):
    MODEL_PATH = "/models/health_predictor.pkl"

class HealthForecaster:
    """Service to run health predictions using the trained Random Forest model."""

    def __init__(self, model_path: str = MODEL_PATH):
        self.model_path = model_path
        self.model_data = None
        self.model = None
        self.gender_mapping = {}
        self.activity_mapping = {}
        self.sleep_mapping = {}
        self.features = []
        self._load_model()

    def _load_model(self) -> None:
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model file not found at '{self.model_path}'. Run training first.")
        with open(self.model_path, "rb") as f:
            self.model_data = pickle.load(f)
        self.model = self.model_data["model"]
        self.features = self.model_data["features"]
        self.gender_mapping = self.model_data["gender_mapping"]
        self.activity_mapping = self.model_data["activity_mapping"]
        self.sleep_mapping = self.model_data["sleep_mapping"]

    def _predict_change_kg(self, input_dict: Dict[str, float]) -> float:
        feature_vector = [input_dict[feat] for feat in self.features]
        df_features = pd.DataFrame([feature_vector], columns=self.features)
        predicted_change_lbs = float(self.model.predict(df_features)[0])
        return predicted_change_lbs / 2.20462

    def _global_feature_importance(self) -> Dict[str, float]:
        if not hasattr(self.model, "feature_importances_"):
            return {}

        telemetry_mapping = {
            "Stress Level": "Stress Level",
            "Daily Caloric Surplus/Deficit": "Caloric Surplus/Deficit",
            "Sleep_encoded": "Sleep Quality",
            "Activity_encoded": "Physical Activity Level",
            "Daily Calories Consumed": "Calories Consumed",
            "Duration (weeks)": "Duration",
            "Gender_encoded": "Gender"
        }
        feature_importance = {}
        for feat, imp in zip(self.features, self.model.feature_importances_):
            telemetry_key = telemetry_mapping.get(feat, feat)
            feature_importance[telemetry_key] = round(float(imp), 4)
        return feature_importance

    def _personalized_feature_importance(
        self,
        calories: float,
        surplus: float,
        gender_encoded: float,
        activity: str,
        activity_encoded: float,
        sleep: str,
        sleep_encoded: float,
        stress: float,
    ) -> Dict[str, float]:
        """Estimate local, profile-specific impact by perturbing one factor at a time."""
        base_input = {
            "Daily Calories Consumed": calories,
            "Daily Caloric Surplus/Deficit": surplus,
            "Duration (weeks)": 4.0,
            "Gender_encoded": float(gender_encoded),
            "Activity_encoded": float(activity_encoded),
            "Sleep_encoded": float(sleep_encoded),
            "Stress Level": float(stress)
        }

        def predict_with(changes: Dict[str, float]) -> float:
            candidate = base_input.copy()
            candidate.update({k: v for k, v in changes.items() if k in candidate})
            return self._predict_change_kg(candidate)

        base_change = self._predict_change_kg(base_input)

        calorie_step = 300.0
        calories_plus = predict_with({
            "Daily Calories Consumed": calories + calorie_step,
            "Daily Caloric Surplus/Deficit": surplus + calorie_step,
        })
        calories_minus = predict_with({
            "Daily Calories Consumed": max(800.0, calories - calorie_step),
            "Daily Caloric Surplus/Deficit": surplus - calorie_step,
        })
        model_calorie_impact = (abs(calories_plus - base_change) + abs(calories_minus - base_change)) / 2.0
        energy_balance_impact = (calorie_step * 7.0 * 4.0) / 7700.0

        stress_plus = predict_with({"Stress Level": min(10.0, stress + 2.0)})
        stress_minus = predict_with({"Stress Level": max(1.0, stress - 2.0)})
        stress_impact = (abs(stress_plus - base_change) + abs(stress_minus - base_change)) / 2.0

        sleep_impact = 0.0
        for value in self.sleep_mapping.values():
            value = float(value)
            if value != float(sleep_encoded):
                sleep_impact = max(sleep_impact, abs(predict_with({"Sleep_encoded": value}) - base_change))

        activity_impact = 0.0
        for value in self.activity_mapping.values():
            value = float(value)
            if value != float(activity_encoded):
                activity_impact = max(activity_impact, abs(predict_with({"Activity_encoded": value}) - base_change))

        sleep_penalty = {
            "Poor": 1.25,
            "Fair": 1.05,
            "Good": 0.85,
            "Excellent": 0.70,
        }.get(str(sleep), 1.0)
        activity_penalty = {
            "Sedentary": 1.25,
            "Lightly Active": 1.05,
            "Moderately Active": 0.85,
            "Very Active": 0.70,
        }.get(str(activity), 1.0)

        raw_scores = {
            "Caloric Surplus/Deficit": max(model_calorie_impact, energy_balance_impact) * (1.0 + min(abs(surplus) / 800.0, 1.0)),
            "Stress Level": max(stress_impact, 0.01) * (0.5 + min(max(stress, 1.0), 10.0) / 10.0),
            "Sleep Quality": max(sleep_impact, 0.01) * sleep_penalty,
            "Physical Activity Level": max(activity_impact, 0.01) * activity_penalty,
        }

        total = sum(raw_scores.values())
        if total <= 0:
            return self._global_feature_importance()
        return {key: round(value / total, 4) for key, value in raw_scores.items()}

    def predict_weekly_trend(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a 5-week trajectory forecast (W0 to W4) for weight and BMI."""
        weight_kg = float(data["current_weight_kg"])
        height_cm = float(data["height_cm"])
        gender = data["gender"]
        activity = data["physical_activity_level"]
        calories = float(data["daily_calories_consumed"])
        surplus = float(data["daily_caloric_surplus"])
        sleep = data["sleep_quality"]
        stress = float(data["stress_level"])

        # Encode categorical inputs
        gender_encoded = self.gender_mapping.get(gender)
        activity_encoded = self.activity_mapping.get(activity)
        sleep_encoded = self.sleep_mapping.get(sleep)

        if gender_encoded is None:
            raise ValueError(f"Invalid gender '{gender}'. Must be 'M' or 'F'.")
        if activity_encoded is None:
            raise ValueError(f"Invalid activity level '{activity}'.")
        if sleep_encoded is None:
            raise ValueError(f"Invalid sleep quality '{sleep}'.")

        height_m = height_cm / 100.0
        bmi_w0 = weight_kg / (height_m ** 2)

        # Baseline week (timeline: "Hiện tại")
        forecast_chart_data = [
            {
                "timeline": "Hiện tại",
                "predicted_weight": round(weight_kg, 2),
                "predicted_bmi": round(bmi_w0, 2)
            }
        ]

        # Call prediction model for Weeks 1 to 4
        previous_weight_kg = weight_kg
        for week in range(1, 5):
            input_dict = {
                "Daily Calories Consumed": calories,
                "Daily Caloric Surplus/Deficit": surplus,
                "Duration (weeks)": float(week),
                "Gender_encoded": float(gender_encoded),
                "Activity_encoded": float(activity_encoded),
                "Sleep_encoded": float(sleep_encoded),
                "Stress Level": float(stress)
            }

            predicted_change_kg = self._predict_change_kg(input_dict)

            # Keep the displayed trajectory consistent with the user's calorie balance.
            # The RF model can occasionally return an opposite-signed change for sparse
            # combinations; in that case use a standard energy-balance estimate.
            energy_balance_change_kg = (surplus * 7.0 * float(week)) / 7700.0
            if surplus < -50.0 and predicted_change_kg > 0.0:
                predicted_change_kg = energy_balance_change_kg
            elif surplus > 50.0 and predicted_change_kg < 0.0:
                predicted_change_kg = energy_balance_change_kg

            predicted_weight_kg = weight_kg + predicted_change_kg
            if surplus < -50.0:
                predicted_weight_kg = min(predicted_weight_kg, previous_weight_kg)
            elif surplus > 50.0:
                predicted_weight_kg = max(predicted_weight_kg, previous_weight_kg)
            previous_weight_kg = predicted_weight_kg
            predicted_bmi = predicted_weight_kg / (height_m ** 2)

            forecast_chart_data.append({
                "timeline": f"Tuần {week}",
                "predicted_weight": round(predicted_weight_kg, 2),
                "predicted_bmi": round(predicted_bmi, 2)
            })

        feature_importance = self._personalized_feature_importance(
            calories=calories,
            surplus=surplus,
            gender_encoded=float(gender_encoded),
            activity=activity,
            activity_encoded=float(activity_encoded),
            sleep=sleep,
            sleep_encoded=float(sleep_encoded),
            stress=stress,
        )

        return {
            "status": "success",
            "current_weight": round(weight_kg, 2),
            "weight_unit": "kg",
            "daily_caloric_surplus": round(surplus, 2),
            "forecast_chart_data": forecast_chart_data,
            "feature_importance": feature_importance,
            "feature_importance_global": self._global_feature_importance()
        }
