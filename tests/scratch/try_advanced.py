import pandas as pd
import numpy as np
import os
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split, KFold, cross_val_score

df = pd.read_csv(os.path.join("data", "raw", "weight_change_dataset.csv"))

gender_map = {"M": 1, "F": 0}
activity_map = {"Sedentary": 0, "Lightly Active": 1, "Moderately Active": 2, "Very Active": 3}
sleep_map = {"Poor": 0, "Fair": 1, "Good": 2, "Excellent": 3}

df["Gender_encoded"] = df["Gender"].map(gender_map)
df["Activity_encoded"] = df["Physical Activity Level"].map(activity_map)
df["Sleep_encoded"] = df["Sleep Quality"].map(sleep_map)

# Let's try training with different models
y = df["Weight Change (lbs)"]
X = df[[
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
]]

# Split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Try Random Forest
rf = RandomForestRegressor(n_estimators=100, random_state=42)
rf.fit(X_train, y_train)
kf = KFold(n_splits=5, shuffle=True, random_state=42)
cv_rf = cross_val_score(rf, X, y, cv=kf, scoring="r2").mean()
print(f"Random Forest Regressor (All Features):")
print(f"  Train R2: {rf.score(X_train, y_train)*100:.2f}%")
print(f"  Test R2: {rf.score(X_test, y_test)*100:.2f}%")
print(f"  CV R2: {cv_rf*100:.2f}%")

# Try Polynomial Features + Ridge
pipe = Pipeline([
    ("poly", PolynomialFeatures(degree=2, include_bias=False)),
    ("scaler", StandardScaler()),
    ("ridge", Ridge(alpha=10.0))
])
pipe.fit(X_train, y_train)
cv_poly = cross_val_score(pipe, X, y, cv=kf, scoring="r2").mean()
print(f"Polynomial Ridge (All Features):")
print(f"  Train R2: {pipe.score(X_train, y_train)*100:.2f}%")
print(f"  Test R2: {pipe.score(X_test, y_test)*100:.2f}%")
print(f"  CV R2: {cv_poly*100:.2f}%")

# Let's look at what is in the dataset that causes Weight Change.
# Is it possible that Weight Change is simply Final Weight - Current Weight, which is not what we want to predict?
# Yes, Weight Change is the TARGET. But in real life, we don't have Final Weight. We want to predict Weight Change.
# Let's inspect the correlation of Final Weight and Current Weight.
print("\nCorrelation of Current Weight and Final Weight:")
print(df[["Current Weight (lbs)", "Final Weight (lbs)"]].corr())
