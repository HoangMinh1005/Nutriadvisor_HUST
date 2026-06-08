import pandas as pd
import numpy as np
import os
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split

df = pd.read_csv(os.path.join("data", "raw", "weight_change_dataset.csv"))

gender_map = {"M": 1, "F": 0}
activity_map = {"Sedentary": 0, "Lightly Active": 1, "Moderately Active": 2, "Very Active": 3}
df["Gender_encoded"] = df["Gender"].map(gender_map)
df["Activity_encoded"] = df["Physical Activity Level"].map(activity_map)

features = ["Daily Caloric Surplus/Deficit", "Duration (weeks)", "Gender_encoded", "Activity_encoded"]
X = df[features]
y = df["Weight Change (lbs)"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = LinearRegression().fit(X_train, y_train)

# Predict on test set
y_pred = model.predict(X_test)

results = pd.DataFrame({
    "Actual": y_test,
    "Predicted": y_pred,
    "Residual": y_test - y_pred,
    "Abs_Residual": np.abs(y_test - y_pred)
})
print("Test set size:", len(results))
print("\nSorted by absolute residual (largest errors first):")
print(results.sort_values(by="Abs_Residual", ascending=False).head(10))

print("\nFull test set details:")
test_idx = y_test.index
test_full = df.loc[test_idx].copy()
test_full["Predicted"] = y_pred
test_full["Abs_Residual"] = np.abs(y_test - y_pred)
print(test_full[["Gender", "Daily Caloric Surplus/Deficit", "Duration (weeks)", "Physical Activity Level", "Weight Change (lbs)", "Predicted", "Abs_Residual"]])
