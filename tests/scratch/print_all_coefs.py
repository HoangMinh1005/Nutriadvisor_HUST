import pandas as pd
import numpy as np
import os
from sklearn.linear_model import LinearRegression

df = pd.read_csv(os.path.join("data", "raw", "weight_change_dataset.csv"))

gender_map = {"M": 1, "F": 0}
activity_map = {"Sedentary": 0, "Lightly Active": 1, "Moderately Active": 2, "Very Active": 3}
sleep_map = {"Poor": 0, "Fair": 1, "Good": 2, "Excellent": 3}

df["Gender_encoded"] = df["Gender"].map(gender_map)
df["Activity_encoded"] = df["Physical Activity Level"].map(activity_map)
df["Sleep_encoded"] = df["Sleep Quality"].map(sleep_map)

features = [
    "Age",
    "Gender_encoded",
    "Current Weight (lbs)",
    "BMR (Calories)",
    "Daily Calories Consumed",
    "Daily Caloric Surplus/Deficit",
    "Duration (weeks)",
    "Activity_encoded",
    "Sleep_encoded",
    "Stress Level"
]

X = df[features]
y = df["Weight Change (lbs)"]

model = LinearRegression().fit(X, y)

print("Coefficients for all features:")
for feature_name, coef in zip(features, model.coef_):
    print(f"  {feature_name:<30}: {coef:.6f}")
print(f"  Intercept: {model.intercept_:.6f}")
print(f"  R2 score on whole dataset: {model.score(X, y)*100:.2f}%")
