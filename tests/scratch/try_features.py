import pandas as pd
import numpy as np
import os
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split, KFold, cross_val_score

df = pd.read_csv(os.path.join("data", "raw", "weight_change_dataset.csv"))

# Encoding maps
gender_map = {"M": 1, "F": 0}
activity_map = {"Sedentary": 0, "Lightly Active": 1, "Moderately Active": 2, "Very Active": 3}
sleep_map = {"Poor": 0, "Fair": 1, "Good": 2, "Excellent": 3}

df["Gender_encoded"] = df["Gender"].map(gender_map)
df["Activity_encoded"] = df["Physical Activity Level"].map(activity_map)
df["Sleep_encoded"] = df["Sleep Quality"].map(sleep_map)

# Let's try training with different sets of features to see what predicts Weight Change (lbs)
y = df["Weight Change (lbs)"]

# All candidate features (excluding Final Weight, and Participant ID)
all_features = [
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

print("Trying individual features R2:")
for f in all_features:
    X = df[[f]]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    m = LinearRegression().fit(X_train, y_train)
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    cv = cross_val_score(m, X, y, cv=kf, scoring="r2").mean()
    print(f"Feature: {f:<30} | Train R2: {m.score(X_train, y_train)*100:6.2f}% | Test R2: {m.score(X_test, y_test)*100:6.2f}% | CV R2: {cv*100:6.2f}%")

# Let's try combinations
features_combos = [
    ["Daily Caloric Surplus/Deficit", "Duration (weeks)", "Gender_encoded", "Activity_encoded"],
    ["Daily Caloric Surplus/Deficit", "Duration (weeks)", "Gender_encoded", "Activity_encoded", "Stress Level", "Sleep_encoded"],
    ["Stress Level", "Sleep_encoded"],
    ["Stress Level", "Sleep_encoded", "Duration (weeks)"],
    ["Stress Level", "Sleep_encoded", "Duration (weeks)", "Gender_encoded"],
    all_features
]

print("\nTrying combinations:")
for combo in features_combos:
    X = df[combo]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    m = LinearRegression().fit(X_train, y_train)
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    cv = cross_val_score(m, X, y, cv=kf, scoring="r2").mean()
    print(f"Features: {str(combo):<80} | Train R2: {m.score(X_train, y_train)*100:6.2f}% | Test R2: {m.score(X_test, y_test)*100:6.2f}% | CV R2: {cv*100:6.2f}%")
