# Project Refactoring Plan: Migrating to the Viện Dinh Dưỡng (VDD) Dataset

This document details the architecture and step-by-step plan for migrating the NutriAdvisor HUST codebase from the legacy NIN + Kaggle merged dataset (~9609 foods) to the newly crawled, cleaned, and 100g-normalized Viện Dinh Dưỡng (VDD) dataset (853 foods).

## 1. Background & Context
The current dataset has several issues:
- **Unclean Portion Sizes**: Many food items are not normalized to standard 100g edible portions, leading to inaccurate solver recommendations.
- **Data Noise**: 9609 rows contain duplicates, unmapped English translations, and missing nutrient parameters.
- **Noisy Categories**: Categories in the legacy database are unstructured, making tagging and constraint enforcement in CSP complex.

The newly crawled VDD dataset (`data/raw/viendinhduong_nutrients.csv`) solves these issues:
- **100% Normalized**: All 853 food items are precisely calculated per 100g edible portion.
- **Clean Grouping**: Standardized categories exist in both Vietnamese and English (e.g., `Ngũ cốc và sản phẩm chế biến`, `Sữa và sản phẩm chế biến`).
- **Comprehensive Nutrients**: Clean mapping for protein, fat, carbs, energy (kcal), and key vitamins/minerals.

---

## 2. Proposed Changes

### Component 1: Database Seeders & Migration

#### [MODIFY] [load_structured_to_db.py](file:///d:/Minh/NutriAdvisor_HUST/data/scripts/load_structured_to_db.py)
Update the database seeder to process the new VDD dataset:
1. Change `DEFAULT_STRUCTURED_PATH` to point to `data/raw/viendinhduong_nutrients.csv`.
2. Update `FOOD_GROUP_MAP` to handle VDD categories:
   ```python
   FOOD_GROUP_MAP = {
       "Sữa và sản phẩm chế biến": "sua_che_pham",
       "Ngũ cốc và sản phẩm chế biến": "tinh_bot",
       "Đồ hộp": "khac",
       "Đồ ngọt (đường, bánh, mứt, kẹo)": "do_an_vat",
       "Gia vị, nước chấm": "khac",
       "Nước giải khát": "giai_khat",
       "Rau, quả và sản phẩm chế biến": "rau_cu",
       "Thịt, thủy sản và sản phẩm chế biến": "thit_do",  # Map to base groups or split
       # ...
   }
   ```
3. Update database constraints and logic to reflect VDD rows (e.g., source priority and standard tags).

---

### Component 2: Feature Store Re-Snapshoting

#### [MODIFY] [extract_features.py](file:///d:/Minh/NutriAdvisor_HUST/backend/ml/feature_store/extract_features.py)
Re-build and cache the ML feature store snapshot:
- Execute `FeatureStore.build_snapshot()` to generate the new `food_feature_snapshot.pkl`.
- The number of features remains 14D, but the matrix rows will count **853** instead of 9609.

---

### Component 3: KNN Recommender Tuning

#### [MODIFY] [knn_recommender.py](file:///d:/Minh/NutriAdvisor_HUST/backend/ml/recsys/knn_recommender.py)
Adjust KNN recommendations for a smaller candidate pool:
1. In `recommend_for_profile(user_profile, n=200)`, reduce the candidate pool size from `200` to `100` or `120` to prevent over-filtering.
2. Adjust stratified diversity rules to ensure the smaller VDD categories are not empty in the returned candidates.

---

### Component 4: CSP Solver & Tagging Rules

#### [MODIFY] [scheduler.py](file:///d:/Minh/NutriAdvisor_HUST/csp/scheduler.py)
Update category classification and tagging heuristics:
1. Refine `get_dynamic_tags()` to handle the new VDD categories:
   - Identify protein sources (`role_protein`) and carb sources (`role_carb`) based on VDD category names.
   - Adjust servings size limits (`get_max_serving_g`) to align with VDD food categories.
2. In `_solve()`, set the maximum domain size constraint `MAX_DOMAIN_SIZE = 150` (instead of 350) since the total VDD pool is 853 items, making backtracking extremely fast (< 0.5 seconds).

---

### Component 5: Tests Adaptation

#### [MODIFY] [test_feature_store_integration.py](file:///d:/Minh/NutriAdvisor_HUST/tests/integration/test_feature_store_integration.py)
- Change assertions from expecting `9609` foods to expecting `853` foods:
  ```python
  assert len(extracted) == 853
  assert matrix.shape == (853, 14)
  ```

#### [MODIFY] [test_meal_plan_pipeline.py](file:///d:/Minh/NutriAdvisor_HUST/tests/integration/test_meal_plan_pipeline.py)
- Update tests to assert correctness using VDD candidates.

---

## 3. Verification Plan

### Database Refresh
1. Run Postgres database reset and seed the VDD database:
   ```bash
   # Reset PostgreSQL volumes
   docker compose down
   docker volume rm nutriadvisor_hust_postgres_data
   docker compose up -d --build
   
   # Load the VDD dataset to PostgreSQL
   .venv\Scripts\python.exe data/scripts/load_structured_to_db.py
   ```

### Rebuild Features
1. Execute backend check or rebuild snapshot script to verify features:
   ```bash
   .venv\Scripts\python.exe -c "from backend.ml.feature_store.extract_features import FeatureStore; FeatureStore().build_snapshot()"
   ```

### Run Automated Tests
1. Verify database and solver integrity using pytest:
   ```bash
   .venv\Scripts\pytest.exe
   ```

### Manual Verification
1. Run `tests/scratch/test_user_flow.py` and inspect the meals generated to verify portions, variety, and nutritional accuracy.
