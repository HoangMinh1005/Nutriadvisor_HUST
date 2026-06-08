import os
import sys
import pickle
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split, KFold, cross_val_score

def run_pipeline():
    print("=== STARTING ML PIPELINE: HEALTH PREDICTION MODEL ===")

    # 1. PRE-EXECUTION VALIDATION
    raw_data_dir = os.path.join("data", "raw")
    dataset_path = os.path.join(raw_data_dir, "weight_change_dataset.csv")

    if not os.path.exists(raw_data_dir):
        print(f"ERROR: Raw data directory '{raw_data_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(dataset_path):
        print(f"ERROR: Target dataset file '{dataset_path}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Validation successful: '{dataset_path}' found.")

    # 2. ETL / DATA PREPROCESSING
    # Load raw dataset
    df_raw = pd.read_csv(dataset_path)
    raw_row_count = len(df_raw)
    print(f"ETL: Number of raw data rows loaded: {raw_row_count}")

    # Clean data (remove rows with missing target or crucial features, drop duplicates)
    required_cols = [
        "Daily Calories Consumed",
        "Daily Caloric Surplus/Deficit",
        "Duration (weeks)",
        "Gender",
        "Physical Activity Level",
        "Sleep Quality",
        "Stress Level",
        "Weight Change (lbs)"
    ]
    df_clean = df_raw.dropna(subset=required_cols).drop_duplicates()
    clean_row_count = len(df_clean)
    print(f"ETL: Number of clean data rows retained: {clean_row_count}")

    # Explicit qualitative encodings
    gender_mapping = {"M": 1, "F": 0}
    activity_mapping = {
        "Sedentary": 0,
        "Lightly Active": 1,
        "Moderately Active": 2,
        "Very Active": 3
    }
    sleep_mapping = {
        "Poor": 0,
        "Fair": 1,
        "Good": 2,
        "Excellent": 3
    }

    print(f"ETL: Gender qualitative encoding map: {gender_mapping}")
    print(f"ETL: Physical Activity Level qualitative encoding map: {activity_mapping}")
    print(f"ETL: Sleep Quality qualitative encoding map: {sleep_mapping}")

    # Map categorical columns
    df_clean["Gender_encoded"] = df_clean["Gender"].map(gender_mapping)
    df_clean["Activity_encoded"] = df_clean["Physical Activity Level"].map(activity_mapping)
    df_clean["Sleep_encoded"] = df_clean["Sleep Quality"].map(sleep_mapping)

    # Re-verify no NaN was introduced during mapping
    cols_to_check = ["Gender_encoded", "Activity_encoded", "Sleep_encoded"]
    if df_clean[cols_to_check].isnull().any().any():
        print("ERROR: Categorical mapping produced NaN values. Check values in raw CSV.", file=sys.stderr)
        sys.exit(1)

    # 3. FEATURE SELECTION & SPLIT
    features = [
        "Daily Calories Consumed",
        "Daily Caloric Surplus/Deficit",
        "Duration (weeks)",
        "Gender_encoded",
        "Activity_encoded",
        "Sleep_encoded",
        "Stress Level"
    ]
    target = "Weight Change (lbs)"

    X = df_clean[features]
    y = df_clean[target]

    # Split dataset into 80% train and 20% test (fixed seed for deterministic results)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # 4. MODEL COMPARISON
    # Model 1: Linear Regression
    lr_model = LinearRegression()
    lr_model.fit(X_train, y_train)
    lr_train_r2 = lr_model.score(X_train, y_train)
    lr_test_r2 = lr_model.score(X_test, y_test)
    
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    lr_cv_scores = cross_val_score(lr_model, X, y, cv=kf, scoring="r2")
    lr_mean_cv = np.mean(lr_cv_scores)

    print("\n--- Model 1: Linear Regression ---")
    print(f"Train R2: {lr_train_r2 * 100:.2f}%")
    print(f"Test R2: {lr_test_r2 * 100:.2f}%")
    print(f"K-Fold CV Mean R2: {lr_mean_cv * 100:.2f}%")

    # Model 2: Random Forest Regressor
    rf_model = RandomForestRegressor(n_estimators=100, max_depth=5, min_samples_split=4, random_state=42)
    rf_model.fit(X_train, y_train)
    rf_train_r2 = rf_model.score(X_train, y_train)
    rf_test_r2 = rf_model.score(X_test, y_test)
    
    rf_cv_scores = cross_val_score(rf_model, X, y, cv=kf, scoring="r2")
    rf_mean_cv = np.mean(rf_cv_scores)

    print("\n--- Model 2: Random Forest Regressor ---")
    print(f"Train R2: {rf_train_r2 * 100:.2f}%")
    print(f"Test R2: {rf_test_r2 * 100:.2f}%")
    print(f"K-Fold CV Mean R2: {rf_mean_cv * 100:.2f}%")

    # 5. MODEL SELECTION & SERIALIZATION
    model_dir = "models"
    os.makedirs(model_dir, exist_ok=True)
    model_output_path = os.path.join(model_dir, "health_predictor.pkl")

    best_model_name = "Random Forest" if rf_test_r2 > lr_test_r2 else "Linear Regression"
    print(f"\nModel Selection: '{best_model_name}' selected based on superior Test R2 ({max(rf_test_r2, lr_test_r2)*100:.2f}%)")

    model_payload = {
        "model_type": best_model_name,
        "features": features,
        "target": target,
        "gender_mapping": gender_mapping,
        "activity_mapping": activity_mapping,
        "sleep_mapping": sleep_mapping
    }

    if best_model_name == "Random Forest":
        model_payload["model"] = rf_model
        model_payload["train_r2"] = rf_train_r2
        model_payload["test_r2"] = rf_test_r2
        model_payload["mean_cv_score"] = rf_mean_cv
    else:
        model_payload["model"] = lr_model
        model_payload["train_r2"] = lr_train_r2
        model_payload["test_r2"] = lr_test_r2
        model_payload["mean_cv_score"] = lr_mean_cv
        model_payload["coefficients"] = dict(zip(features, lr_model.coef_))
        model_payload["intercept"] = lr_model.intercept_

    with open(model_output_path, "wb") as f:
        pickle.dump(model_payload, f)

    print(f"EXPORT: Best model successfully saved to '{model_output_path}'")
    print("=== PIPELINE RUN COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_pipeline()
