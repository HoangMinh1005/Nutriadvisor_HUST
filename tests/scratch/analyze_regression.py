import pandas as pd
import numpy as np
import os

df = pd.read_csv(os.path.join("data", "raw", "weight_change_dataset.csv"))
print("Dataset columns:", list(df.columns))

# Convert Gender and Activity Level
gender_map = {"M": 1, "F": 0}
activity_map = {"Sedentary": 0, "Lightly Active": 1, "Moderately Active": 2, "Very Active": 3}
df["Gender_encoded"] = df["Gender"].map(gender_map)
df["Activity_encoded"] = df["Physical Activity Level"].map(activity_map)

# Exclude non-numeric columns for correlation
numeric_df = df.select_dtypes(include=[np.number])
print("\nCorrelation with Weight Change (lbs):")
print(numeric_df.corr()["Weight Change (lbs)"].sort_values(ascending=False))

# Let's check some simple statistics of the dataset
print("\nDescriptive statistics:")
print(df[["Daily Caloric Surplus/Deficit", "Duration (weeks)", "Weight Change (lbs)"]].describe())

# Check how Weight Change behaves
# Weight Change should theoretically be linked to Daily Caloric Surplus/Deficit * Duration (weeks)
df["Caloric_Surplus_x_Duration"] = df["Daily Caloric Surplus/Deficit"] * df["Duration (weeks)"]
print("\nCorrelation of interaction term with Weight Change:")
print(df[["Caloric_Surplus_x_Duration", "Weight Change (lbs)"]].corr().iloc[0, 1])

# Is there any other relationship?
# Let's train a model with interaction term
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
X_int = df[["Caloric_Surplus_x_Duration", "Gender_encoded", "Activity_encoded"]]
y = df["Weight Change (lbs)"]
X_train, X_test, y_train, y_test = train_test_split(X_int, y, test_size=0.2, random_state=42)
m = LinearRegression()
m.fit(X_train, y_train)
print("\nWith interaction term:")
print(f"Train R2: {m.score(X_train, y_train)*100:.2f}%")
print(f"Test R2: {m.score(X_test, y_test)*100:.2f}%")
