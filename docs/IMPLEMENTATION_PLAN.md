# Kế Hoạch Triển Khai Chi Tiết - NutriAdvisor

**Dự án:** Hệ thống tư vấn dinh dưỡng cá nhân  
**Phiên bản:** v1.1.0  
**Ngày cập nhật:** 2026-04-29  
**Trạng thái:** Pha 1-4 hoàn thành ✅, sẵn sàng Pha 5-6 (ML Ecosystem & Frontend)

---

## I. Tổng Quan Kiến Trúc

### 1.1 Cấu Trúc Dữ Liệu (Đã hoàn thành)
```
┌─────────────────────────────────────────────────────┐
│ INPUT: NIN (1250) + Kaggle (8684) = 9934 rows      │
├─────────────────────────────────────────────────────┤
│ LAYER 1: food_source_rows (RAW) - 9934 dòng        │
│ → Giữ 100% dữ liệu gốc, lineage traceability        │
├─────────────────────────────────────────────────────┤
│ LAYER 2: foods (CANONICAL) - 9609 dòng             │
│ → Dedupe theo canonical_key                        │
│ → food_id liên tục 1→9609                          │
├─────────────────────────────────────────────────────┤
│ LAYER 3: food_nutrients (VECTORS) - 9609 dòng      │
│ → 14 nutrient fields + confidence scores           │
├─────────────────────────────────────────────────────┤
│ LAYER 4: food_aliases (SEARCH INDEX) - 1913 dòng   │
│ → VI non-diacritic + synonyms                      │
└─────────────────────────────────────────────────────┘
```

### 1.2 Kiến Trúc Backend
```
FastAPI (:8000)
├── /foods/search?q=...
│   ├── Exact tier (food_aliases)
│   ├── Fuzzy tier (pg_trgm similarity)
│   └── Fallback tier
└── Search response: {food_id, canonical_name_en, nutrients[], match_score}
```

---

## II. Các Pha Triển Khai

### ✅ **Pha 1: ETL & Data Foundation** (HOÀN THÀNH)

**Mục tiêu:** Chuẩn hóa dữ liệu và xây dựng kho dữ liệu chuẩn.

**Các bước đã thực hiện:**
1. ✅ Merge NIN + Kaggle → `final_nutrients_structured.csv`
2. ✅ Tạo canonical keys (EN-first) + VI aliases
3. ✅ Schema 5 bảng chính: foods, food_nutrients, food_aliases, food_source_rows, dataset_versions
4. ✅ Migration runner với checksum tracking
5. ✅ Loader với dedupe và contiguous ID assignment
6. ✅ Docker Compose: Postgres (port 5433) + pgAdmin + Backend

**Artifacts:**
- `data/raw/final_nutrients_structured.csv` (9934 rows)
- `data/raw/food_aliases_vi.csv` (1913 rows)
- `data/raw/dataset_version_manifest.json` (v1.1.0)
- `data/sql/init/001_schema.sql` (canonical schema)
- `data/sql/init/004_food_source_rows.sql` (raw staging)
- `data/scripts/run_migrations.py` (idempotent runner)
- `data/scripts/load_structured_to_db.py` (--reset mode)

**Xác nhận chất lượng:**
- `food_source_rows`: 9934 rows (100% input)
- `foods`: 9609 rows (unique canonical_key)
- `food_id` range: 1→9609 (contiguous)
- All nutrients normalized, 14 fields per food

---

### 🔄 **Pha 2: Backend Search & API** (HOÀN THÀNH)

**Mục tiêu:** Cung cấp API search hiệu quả với 3-tier matching.

**Các bước đã thực hiện:**
1. ✅ FastAPI backend tại `/backend`
2. ✅ Food search service: exact → fuzzy → fallback
3. ✅ pg_trgm GIN index trên food_aliases.alias_text
4. ✅ Search response: tier, food_id, canonical_name, nutrients[], match_score
5. ✅ Docker container mapping :8000

**Artifacts:**
- `backend/app/main.py` (FastAPI routes)
- `backend/app/services/food_search.py` (search logic)
- `docker-compose.yml` (3 services)

**Xác nhận chất lượng:**
- `/foods/search?q=thit+bo` → fuzzy results
- Response schema có food_id, calories, protein, fat, carbs
- Match scores normalized 0.0→1.0
- Performance: <500ms per query

---

### 📋 **Pha 3: Test & Validation Framework** (70% - CHỜ HOÀN THÀNH)

**Mục tiêu:** Kiểm tra tự động để phát hiện lệch số hàng, lỗi schema, query sai.

**Các bước cần làm:**

#### 3.1 Unit Tests (Loader & Helpers)
```
tests/
├── test_load_structured_to_db.py
│   ├── test_dedupe_removes_duplicates()
│   ├── test_food_id_contiguous()
│   ├── test_raw_rows_count_equals_input()
│   └── test_canonical_count_matches_unique_keys()
├── test_helpers.py
│   ├── test_clean_text()
│   ├── test_to_float()
│   └── test_to_bool()
└── conftest.py (pytest fixtures)
```

#### 3.2 Integration Tests (End-to-end)
```
tests/integration/
├── test_migration_runner.py
│   ├── test_migration_applied_idempotently()
│   └── test_schema_migrations_tracked()
├── test_api_search.py
│   ├── test_exact_match_returns_high_score()
│   ├── test_fuzzy_match_handles_typo()
│   └── test_fallback_tier_fires()
└── test_data_loader.py
    ├── test_full_load_with_reset()
    └── test_row_counts_after_load()
```

#### 3.3 Validation Queries (SQL)
```sql
-- Kiểm tra tính toàn vẹn dữ liệu
SELECT 
  (SELECT COUNT(*) FROM food_source_rows) as raw_count,
  (SELECT COUNT(*) FROM foods) as canonical_count,
  (SELECT COUNT(*) FROM food_nutrients) as nutrient_count,
  (SELECT COUNT(*) FROM food_aliases) as alias_count;

-- Xác nhận không có orphan rows
SELECT f.food_id FROM foods f 
LEFT JOIN food_nutrients n ON f.food_id = n.food_id 
WHERE n.food_id IS NULL;

-- Xác nhận ID liên tục
SELECT food_id FROM foods 
WHERE food_id NOT IN (SELECT generate_series(1, 9609));
```

**Outputs:**
- `tests/` folder với pytest
- `docs/TESTING.md` (test scenarios)
- Kiểm tra tự động trong CI/CD

**Timeline:** 2-3 ngày

---

### ✅ **Pha 4: CI/CD Pipeline** (100% - HOÀN THÀNH)

**Mục tiêu:** Tự động hóa test, build, deploy trên mỗi commit.

**Status:** ✅ COMPLETE - GitHub Actions workflow created and ready to use

#### 4.1 GitHub Actions Workflow
```yaml
.github/workflows/data-ci.yml:
  - on: [push, pull_request]
  - jobs:
    - lint (flake8, black)
    - unit-tests (pytest tests/)
    - integration-tests (docker compose + smoke test)
    - checksum-verify (migration hashes)
    - coverage-report
```

#### 4.2 Checks
1. SQL syntax validation
2. CSV schema validation (14 columns)
3. Data count assertion: raw=9934, canonical=9609
4. API smoke test: `/foods/search?q=test`
5. Performance baseline: query <500ms

**Artifacts:**
- `.github/workflows/data-ci.yml`
- `requirements-test.txt` (pytest, coverage)
- `scripts/run_ci_checks.sh`

**Timeline:** 2 ngày

---

### 🤖 **Pha 5: ML/CSP Ecosystem & Meal Planning** (0% - FUTURE)

**Mục tiêu:** Xây dựng 5-module ML system để tư vấn bữa ăn cá nhân hóa + dự báo sức khỏe.

**Kiến trúc tổng quan:**
```
User Intent (NLP Engine) 
    ↓
User Segmentation (K-Means) 
    ↓
Food Recommendation (KNN RecSys)
    ↓
Meal Planning (CSP Optimization)
    ↓
Health Prediction (Linear Regression) + Feedback
```

---

#### **5.1 Feature Engineering & Feature Store** (Week 1 - ✅ HOÀN THÀNH)

**Mục tiêu:** Xây dựng foundation cho tất cả 5 modules.

**Trạng thái:** ✅ Extract, normalize, cache, and test đã hoàn thành.

**5.1.1 Extract & Transform from DB**
```python
# backend/ml/feature_store/extract_features.py
import pandas as pd
import numpy as np
from pathlib import Path
import psycopg
import pickle

class FeatureStore:
    def __init__(self, db_url):
        self.db_url = db_url
        self.cache_dir = Path("data/ml/features")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def extract_food_vectors(self) -> pd.DataFrame:
        """Extract 14D nutrient vectors for all 9609 foods."""
        conn = psycopg.connect(self.db_url)
        df = pd.read_sql("""
            SELECT 
                f.food_id, f.canonical_key, f.canonical_name_en,
                n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g,
                n.vitamin_a_mcg, n.beta_carotene_mcg, n.vitamin_c_mg,
                n.calcium_mg, n.iron_mg, n.zinc_mg,
                n.sodium_mg, n.cholesterol_mg, n.magnesium_mg
            FROM foods f
            JOIN food_nutrients n ON f.food_id = n.food_id
            ORDER BY f.food_id
        """, conn)
        conn.close()
        return df
    
    def normalize_nutrients(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize nutrient vectors to 0-1 range for ML."""
        nutrient_cols = [
            'energy_kcal', 'protein_g', 'fat_g', 'carbs_g',
            'vitamin_a_mcg', 'beta_carotene_mcg', 'vitamin_c_mg',
            'calcium_mg', 'iron_mg', 'zinc_mg',
            'sodium_mg', 'cholesterol_mg', 'magnesium_mg'
        ]
        
        for col in nutrient_cols:
            min_val = df[col].min()
            max_val = df[col].max()
            if max_val > min_val:
                df[col] = (df[col] - min_val) / (max_val - min_val)
            else:
                df[col] = 0.0
        
        return df
    
    def cache_features(self, name: str, data):
        """Cache features to disk for ML training."""
        cache_file = self.cache_dir / f"{name}.pkl"
        with open(cache_file, 'wb') as f:
            pickle.dump(data, f)
    
    def load_cached_features(self, name: str):
        """Load cached features."""
        cache_file = self.cache_dir / f"{name}.pkl"
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
```

**5.1.2 Create Feature Schema**
```python
# backend/ml/feature_store/schemas.py

class FoodFeatureVector:
    """14D feature vector per food."""
    food_id: int
    canonical_key: str
    energy_kcal_norm: float  # 0-1
    protein_g_norm: float
    fat_g_norm: float
    carbs_g_norm: float
    vitamin_a_mcg_norm: float
    beta_carotene_mcg_norm: float
    vitamin_c_mg_norm: float
    calcium_mg_norm: float
    iron_mg_norm: float
    zinc_mg_norm: float
    sodium_mg_norm: float
    cholesterol_mg_norm: float
    magnesium_mg_norm: float

class UserProfile:
    """User profile for personalization."""
    user_id: int
    age: int
    gender: str  # M/F
    weight_kg: float
    height_cm: float
    daily_calorie_target: float
    macro_ratios: dict  # {protein: 0.3, fat: 0.3, carbs: 0.4}
    allergies: list[str]  # ["peanut", "shellfish"]
    dietary_preferences: list[str]  # ["vegetarian", "vegan"]
    health_goal: str  # "weight_loss", "muscle_gain", "maintenance"

class MealPlanRequest:
    """User request for meal plan."""
    user_id: int
    num_days: int  # 1-7
    num_meals_per_day: int  # 3-5
    budget_per_day: float  # VND
    cuisine_preferences: list[str]
    excluded_foods: list[int]
```

**Timeline:** Day 1-2 | Output: `data/ml/features/` cache

---

#### **5.2 Module 1: NLP Engine (Hybrid: Local + Free APIs - 100% FREE)** (Week 2)

**Mục tiêu:** Hiểu ý định user từ text query - 100% FREE hybrid approach (Underthesea local + free cloud tiers).

**5.2.1 Hybrid Intent Classification with Underthesea (Free Vietnamese NLP)**
```python
# backend/ml/nlp/intent_engine.py
from underthesea import word_tokenize, ner, sentiment
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
import pickle
import httpx
import os

class IntentEngine:
    """NLP module: Hybrid Underthesea (local, free) + Optional API (free tier only)."""
    
    # Tier 1: Simple intents (train locally with Underthesea)
    LOCAL_INTENTS = {
        "recommend": "recommend_meal",         # "Gợi ý bữa cơm cho tôi"
        "allergies": "allergy_declaration",    # "Tôi bị dị ứng tôm"
        "budget": "budget_constraint",         # "Bữa cơm không quá 50k"
        "cuisine": "cuisine_preference",       # "Tôi thích món Á"
    }
    
    # Tier 2: Complex intents (use FREE cloud tier if local confidence low)
    API_INTENTS = {
        "weight_loss": "weight_loss_goal",     # "Tôi muốn giảm 2kg trong 1 tháng"
        "muscle_gain": "muscle_gain_goal",     # "Tôi muốn tăng cơ"
        "health": "health_goal",               # "Tôi muốn khỏe mạnh"
    }
    
    def __init__(self):
        # Local model
        self.tfidf = TfidfVectorizer(analyzer='char', ngram_range=(2, 3))
        self.clf = MultinomialNB()
        self.local_trained = False
        
        # FREE API (only if local confidence < threshold)
        self.api_provider = os.getenv("NLP_API_PROVIDER", "google")  # google, aws
        self.api_key = os.getenv("NLP_API_KEY", "")
        self.api_endpoint = os.getenv("NLP_API_ENDPOINT", "")
        self.confidence_threshold = 0.85
        self.use_api = bool(self.api_key)  # Only if credentials set
    
    def train(self, training_data: list[tuple]):
        """
        Train LOCAL model on Vietnamese meal-related texts.
        training_data: [(text, intent), ...] for LOCAL_INTENTS only
        """
        texts = [t[0] for t in training_data]
        labels = [t[1] for t in training_data]
        
        X = self.tfidf.fit_transform(texts)
        self.clf.fit(X, labels)
        self.local_trained = True
        
        # Save model for persistence
        self._save_models()
    
    def predict_intent(self, user_query: str) -> dict:
        """Predict intent using HYBRID strategy."""
        if not self.local_trained:
            return {"intent": "unknown", "confidence": 0.0, "source": "error"}
        
        # Tier 1: Try local prediction
        local_result = self._predict_local(user_query)
        
        # Tier 2: If low confidence, try API
        if local_result["confidence"] < self.confidence_threshold:
            api_result = self._predict_via_api(user_query)
            if api_result:
                api_result["source"] = "api"
                return api_result
        
        local_result["source"] = "local"
        return local_result
    
    def _predict_local(self, user_query: str) -> dict:
        """Predict using local sklearn model (simple intents)."""
        X = self.tfidf.transform([user_query])
        intent = self.clf.predict(X)[0]
        confidence = float(self.clf.predict_proba(X).max())
        
        return {
            "intent": intent,
            "confidence": confidence,
            "query": user_query
        }
    
    def _predict_via_api(self, user_query: str) -> dict:
        """Predict using external API for complex intents."""
        try:
            response = httpx.post(
                f"{self.api_endpoint}/analyze",
                json={"text": user_query, "language": "vi"},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=5.0
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "intent": data["intent"],
                    "confidence": data["confidence"],
                    "query": user_query
                }
        except Exception as e:
            print(f"API error: {e}")
        
        return None  # Fallback to local
    
    def extract_entities(self, user_query: str, intent: str = None) -> dict:
        """Extract entities: calories, weight, allergies, etc."""
        import re
        
        entities = {
            "calories": None,
            "weight_loss_kg": None,
            "duration_days": None,
            "budget_vnd": None,
            "allergies": [],
            "cuisines": []
        }
        
        # For complex intents, use API to extract
        if intent in self.API_INTENTS and self.api_endpoint:
            return self._extract_entities_via_api(user_query)
        
        # For simple intents, use regex
        # Extract calories (e.g., "1500 kcal")
        cal_match = re.search(r'(\d{3,4})\s*kcal', user_query)
        if cal_match:
            entities["calories"] = int(cal_match.group(1))
        
        # Extract weight (e.g., "giảm 2kg", "tăng 3kg")
        weight_match = re.search(r'(giảm|tăng)\s*(\d+\.?\d*)\s*kg', user_query)
        if weight_match:
            entities["weight_loss_kg"] = float(weight_match.group(2))
        
        # Extract duration (e.g., "trong 1 tháng" = 30 days)
        duration_map = {
            "ngày": 1, "tuần": 7, "tháng": 30, "năm": 365
        }
        for unit, days in duration_map.items():
            dur_match = re.search(rf'(\d+)\s*{unit}', user_query)
            if dur_match:
                entities["duration_days"] = int(dur_match.group(1)) * days
        
        return entities
    
    def _extract_entities_via_api(self, user_query: str) -> dict:
        """Extract entities using external API (for complex intents)."""
        try:
            response = httpx.post(
                f\"{self.api_endpoint}/extract\",
                json={\"text\": user_query, \"language\": \"vi\"},
                headers={\"Authorization\": f\"Bearer {self.api_key}\"},
                timeout=5.0
            )
            
            if response.status_code == 200:
                return response.json()[\"entities\"]
        except Exception as e:
            print(f\"Entity extraction API error: {e}\")
        
        return {}  # Fallback to empty
    
    def _save_models(self):
        \"\"\"Save trained models to disk.\"\"\"
        import pickle
        pickle.dump(self.tfidf, open(\"models/tfidf.pkl\", \"wb\"))
        pickle.dump(self.clf, open(\"models/classifier.pkl\", \"wb\"))
    
    def _load_models(self):
        \"\"\"Load trained models from disk.\"\"\"
        import pickle
        try:
            self.tfidf = pickle.load(open(\"models/tfidf.pkl\", \"rb\"))
            self.clf = pickle.load(open(\"models/classifier.pkl\", \"rb\"))
            self.local_trained = True
        except FileNotFoundError:
            print(\"Models not found. Please train first.\")
```

**5.2.2 Caching Strategy (Redis Cache for API Results)**
```python
# backend/ml/nlp/cache.py
from redis import Redis
import json
import hashlib

class IntentCache:
    \"\"\"Cache intent predictions to reduce API calls.\"\"\"
    
    def __init__(self, redis_host=\"localhost\", redis_port=6379):
        self.redis = Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.ttl = 86400  # 24 hours
    
    def get_cached_intent(self, query: str) -> dict | None:
        \"\"\"Get cached intent if exists.\"\"\"
        key = self._make_key(query)
        cached = self.redis.get(key)
        if cached:
            return json.loads(cached)
        return None
    
    def cache_intent(self, query: str, result: dict):
        \"\"\"Cache intent prediction.\"\"\"
        key = self._make_key(query)
        self.redis.setex(key, self.ttl, json.dumps(result))
    
    def _make_key(self, query: str) -> str:
        \"\"\"Generate cache key from query.\"\"\"
        return f\"intent:{hashlib.md5(query.encode()).hexdigest()}\"
```

**5.2.3 Free Options - 100% FREE with Underthesea + Free Cloud Tiers**

```env
# OPTION 1: PURE LOCAL (No API, completely free)
NLP_MODE=local_only
NLP_API_ENABLED=false

# OPTION 2: HYBRID (Local + Free tier) - RECOMMENDED
NLP_MODE=hybrid
NLP_API_PROVIDER=google                # Free: 5,000 requests/month
NLP_API_KEY=xxx
NLP_CONFIDENCE_THRESHOLD=0.85

# OR AWS (even more generous)
NLP_API_PROVIDER=aws
```

**Timeline:** Day 3-5 | Output: `backend/ml/nlp/` (intent_engine.py + cache.py)

---

#### **5.3 Module 2: K-Means Clustering (User Segmentation)** (Week 2-3)

**Mục tiêu:** Phân nhóm user để gợi ý "Menu mẫu" phù hợp.

**5.3.1 User Clustering**
```python
# backend/ml/clustering/user_segmentation.py
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import numpy as np

class UserSegmentation:
    """Segment users into K groups for personalized recommendations."""
    
    def __init__(self, n_clusters=5):
        self.n_clusters = n_clusters
        self.kmeans = KMeans(n_clusters=n_clusters, random_state=42)
        self.scaler = StandardScaler()
        self.fitted = False
    
    def extract_user_features(self, users: list[dict]) -> np.ndarray:
        """
        Extract features from user profiles:
        [age, BMI, daily_calorie_target, num_allergies, health_goal_encoded]
        """
        features = []
        for user in users:
            age = user.get('age', 30)
            weight = user.get('weight_kg', 70)
            height = user.get('height_cm', 170)
            bmi = weight / ((height / 100) ** 2)
            
            cal_target = user.get('daily_calorie_target', 2000)
            num_allergies = len(user.get('allergies', []))
            
            health_goal = user.get('health_goal', 'maintenance')
            goal_map = {'weight_loss': 1, 'maintenance': 2, 'muscle_gain': 3}
            goal_encoded = goal_map.get(health_goal, 2)
            
            features.append([age, bmi, cal_target, num_allergies, goal_encoded])
        
        return np.array(features)
    
    def fit_clusters(self, users: list[dict]):
        """Fit K-Means on user features."""
        X = self.extract_user_features(users)
        X_scaled = self.scaler.fit_transform(X)
        self.kmeans.fit(X_scaled)
        self.fitted = True
    
    def predict_cluster(self, user: dict) -> dict:
        """Predict which cluster a user belongs to."""
        if not self.fitted:
            return {"cluster": -1, "segment_name": "unknown"}
        
        X = self.extract_user_features([user])
        X_scaled = self.scaler.transform(X)
        cluster = int(self.kmeans.predict(X_scaled)[0])
        
        segment_names = [
            "budget_conscious",
            "health_focused",
            "performance_athlete",
            "balanced_lifestyle",
            "premium_wellness"
        ]
        
        return {
            "cluster": cluster,
            "segment_name": segment_names[cluster],
            "distance_to_centroid": float(
                np.linalg.norm(X_scaled[0] - self.kmeans.cluster_centers_[cluster])
            )
        }
```

**5.3.2 Menu Templates per Cluster**
```python
# backend/ml/clustering/menu_templates.py
MENU_TEMPLATES = {
    "budget_conscious": {
        "daily_budget_vnd": 50000,
        "cuisine_preference": ["Vietnamese", "Asian"],
        "priority": "cost_effective"
    },
    "health_focused": {
        "daily_budget_vnd": 150000,
        "cuisine_preference": ["Mediterranean", "Organic"],
        "priority": "nutrition_balance"
    },
    "performance_athlete": {
        "daily_budget_vnd": 200000,
        "cuisine_preference": ["High-protein", "Muscle-building"],
        "priority": "macro_optimization"
    },
    "balanced_lifestyle": {
        "daily_budget_vnd": 100000,
        "cuisine_preference": ["Diverse"],
        "priority": "variety"
    },
    "premium_wellness": {
        "daily_budget_vnd": 300000,
        "cuisine_preference": ["Gourmet", "Organic", "Specialty"],
        "priority": "taste_nutrition"
    }
}
```

**Timeline:** Day 6-9 | Output: `backend/ml/clustering/`

---

#### **5.4 Module 3: KNN Recommendation System** (Week 3)

**Mục tiêu:** Gợi ý food alternatives dựa trên nutrient similarity.

**5.4.1 KNN RecSys**
```python
# backend/ml/recsys/knn_recommender.py
from sklearn.neighbors import NearestNeighbors
import numpy as np

class KNNRecommender:
    """Content-based recommendation using nutrient vectors."""
    
    def __init__(self, n_neighbors=5):
        self.n_neighbors = n_neighbors
        self.knn = NearestNeighbors(n_neighbors=n_neighbors, metric='cosine')
        self.food_vectors = None
        self.food_metadata = None
        self.fitted = False
    
    def fit(self, food_vectors: np.ndarray, food_metadata: list[dict]):
        """
        Fit KNN on normalized food vectors.
        
        Args:
            food_vectors: (9609, 14) array of normalized nutrients
            food_metadata: list of {food_id, canonical_key, name_en, ...}
        """
        self.knn.fit(food_vectors)
        self.food_vectors = food_vectors
        self.food_metadata = food_metadata
        self.fitted = True
    
    def recommend(self, query_food_id: int, n: int = 5) -> list[dict]:
        """Recommend N similar foods based on nutrient profile."""
        if not self.fitted:
            return []
        
        query_idx = query_food_id - 1  # food_id starts at 1
        query_vector = self.food_vectors[query_idx:query_idx+1]
        
        distances, indices = self.knn.kneighbors(query_vector, n_neighbors=n+1)
        
        recommendations = []
        for distance, idx in zip(distances[0][1:], indices[0][1:]):  # Skip first (self)
            food = self.food_metadata[idx]
            recommendations.append({
                "food_id": food['food_id'],
                "canonical_key": food['canonical_key'],
                "name_en": food['canonical_name_en'],
                "similarity_score": 1 - distance  # Convert distance to similarity
            })
        
        return recommendations
    
    def recommend_by_constraint(self, target_nutrients: dict, 
                                 exclude_foods: list[int], n: int = 10) -> list[dict]:
        """
        Recommend foods matching target nutrient profile.
        
        target_nutrients: {energy: 250, protein: 25, fat: 10, carbs: 20}
        """
        # Normalize target nutrients to 0-1
        query_vector = self._normalize_target(target_nutrients)
        
        distances, indices = self.knn.kneighbors(
            query_vector.reshape(1, -1), 
            n_neighbors=n * 2
        )
        
        recommendations = []
        for distance, idx in zip(distances[0], indices[0]):
            food = self.food_metadata[idx]
            if food['food_id'] in exclude_foods:
                continue
            
            recommendations.append({
                "food_id": food['food_id'],
                "canonical_key": food['canonical_key'],
                "name_en": food['canonical_name_en'],
                "match_score": 1 - distance
            })
            
            if len(recommendations) >= n:
                break
        
        return recommendations
```

**Timeline:** Day 10-12 | Output: `backend/ml/recsys/knn_recommender.py`

---

#### **5.5 Module 4: CSP Meal Planner (Optimization)** (Week 3-4)

**Mục tiêu:** Giải bài toán xếp 28 bữa ăn thỏa mãn ràng buộc.

**5.5.1 CSP Model**
```python
# backend/ml/optimization/csp_solver.py
from constraint import Problem, AllDifferentConstraint, InSetConstraint
import itertools

class MealPlanCSP:
    """Constraint Satisfaction Problem for 7-day meal planning."""
    
    def __init__(self, user_profile: dict, available_foods: list[dict]):
        self.problem = Problem()
        self.user = user_profile
        self.foods = available_foods
        self.food_by_id = {f['food_id']: f for f in available_foods}
        
    def define_variables(self):
        """Define 28 variables (7 days × 4 meals)."""
        for day in range(7):
            for meal_type in range(4):  # breakfast, lunch, snack, dinner
                var_name = f"day{day}_meal{meal_type}"
                # Domain: list of food_ids
                food_ids = [f['food_id'] for f in self.foods]
                self.problem.addVariable(var_name, food_ids)
    
    def add_diversity_constraint(self):
        """No same food > 2 times per week."""
        variables = [f"day{d}_meal{m}" for d in range(7) for m in range(4)]
        
        def diverse_foods(*values):
            # Count occurrences of each food
            counts = {}
            for food_id in values:
                counts[food_id] = counts.get(food_id, 0) + 1
            # No food appears >2 times
            return all(count <= 2 for count in counts.values())
        
        self.problem.addConstraint(diverse_foods, variables)
    
    def add_calorie_constraint(self):
        """Daily calorie ≈ target ± 10%."""
        target_cal = self.user.get('daily_calorie_target', 2000)
        tolerance = target_cal * 0.1
        
        for day in range(7):
            variables = [f"day{day}_meal{m}" for m in range(4)]
            
            def check_calories(*food_ids):
                total_cal = sum(
                    self.food_by_id[fid].get('energy_kcal', 0) 
                    for fid in food_ids
                )
                return (target_cal - tolerance) <= total_cal <= (target_cal + tolerance)
            
            self.problem.addConstraint(check_calories, variables)
    
    def add_macro_constraint(self):
        """Macro ratios: P:F:C ≈ target ratio ± 5%."""
        target_ratios = self.user.get('macro_ratios', {
            'protein': 0.3, 'fat': 0.3, 'carbs': 0.4
        })
        
        for day in range(7):
            variables = [f"day{day}_meal{m}" for m in range(4)]
            
            def check_macros(*food_ids):
                total_protein = sum(
                    self.food_by_id[fid].get('protein_g', 0) 
                    for fid in food_ids
                )
                total_fat = sum(
                    self.food_by_id[fid].get('fat_g', 0) 
                    for fid in food_ids
                )
                total_carbs = sum(
                    self.food_by_id[fid].get('carbs_g', 0) 
                    for fid in food_ids
                )
                
                total = total_protein + total_fat + total_carbs
                if total == 0:
                    return False
                
                protein_ratio = total_protein / total
                fat_ratio = total_fat / total
                carbs_ratio = total_carbs / total
                
                tolerance = 0.05
                return (
                    abs(protein_ratio - target_ratios['protein']) <= tolerance and
                    abs(fat_ratio - target_ratios['fat']) <= tolerance and
                    abs(carbs_ratio - target_ratios['carbs']) <= tolerance
                )
            
            self.problem.addConstraint(check_macros, variables)
    
    def add_allergy_constraint(self):
        """Respect user allergies."""
        allergies = self.user.get('allergies', [])
        if not allergies:
            return
        
        variables = [f"day{d}_meal{m}" for d in range(7) for m in range(4)]
        
        def no_allergies(*food_ids):
            for food_id in food_ids:
                food = self.food_by_id[food_id]
                if any(allergen in food.get('allergens', []) 
                       for allergen in allergies):
                    return False
            return True
        
        self.problem.addConstraint(no_allergies, variables)
    
    def solve(self, time_limit_sec=30) -> dict:
        """Solve CSP and return 7-day meal plan."""
        self.define_variables()
        self.add_diversity_constraint()
        self.add_calorie_constraint()
        self.add_macro_constraint()
        self.add_allergy_constraint()
        
        try:
            solution = self.problem.getSolution()
            
            # Format solution
            meal_plan = []
            for day in range(7):
                daily_meals = []
                for meal in range(4):
                    var = f"day{day}_meal{meal}"
                    food_id = solution[var]
                    food = self.food_by_id[food_id]
                    daily_meals.append({
                        "meal_type": ["breakfast", "lunch", "snack", "dinner"][meal],
                        "food_id": food_id,
                        "name": food.get('canonical_name_en'),
                        "energy_kcal": food.get('energy_kcal', 0)
                    })
                meal_plan.append({
                    "day": day + 1,
                    "meals": daily_meals
                })
            
            return {
                "status": "success",
                "meal_plan": meal_plan,
                "feasible": True
            }
        
        except Exception as e:
            return {
                "status": "infeasible",
                "error": str(e),
                "feasible": False
            }
```

**Timeline:** Day 13-16 | Output: `backend/ml/optimization/csp_solver.py`

---

#### **5.6 Module 5: Linear Regression (Health Prediction)** (Week 4)

**Mục tiêu:** Dự báo chỉ số sức khỏe tương lai dựa trên lịch sử ăn uống.

**5.6.1 Health Outcome Predictor**
```python
# backend/ml/regression/health_predictor.py
from sklearn.linear_model import LinearRegression
import numpy as np

class HealthOutcomePredictor:
    """Predict future health metrics based on eating history."""
    
    def __init__(self):
        self.bmi_model = LinearRegression()
        self.weight_model = LinearRegression()
        self.energy_model = LinearRegression()
        self.fitted = False
    
    def extract_temporal_features(self, user_eating_history: list[dict]) -> np.ndarray:
        """
        Extract features over time.
        eating_history: [
            {date: "2026-04-01", energy_kcal: 2000, protein_g: 100, ...},
            ...
        ]
        
        Returns: (n_weeks, n_features) array
        """
        # Group by week
        weeks_data = {}
        for entry in user_eating_history:
            week = entry['date'].isocalendar()[1]
            if week not in weeks_data:
                weeks_data[week] = []
            weeks_data[week].append(entry)
        
        features = []
        for week in sorted(weeks_data.keys()):
            week_data = weeks_data[week]
            
            avg_energy = np.mean([e.get('energy_kcal', 0) for e in week_data])
            avg_protein = np.mean([e.get('protein_g', 0) for e in week_data])
            avg_carbs = np.mean([e.get('carbs_g', 0) for e in week_data])
            avg_fat = np.mean([e.get('fat_g', 0) for e in week_data])
            
            features.append([avg_energy, avg_protein, avg_carbs, avg_fat])
        
        return np.array(features)
    
    def train(self, users_history: list[dict]):
        """Train regression models on historical data."""
        X_list = []
        y_bmi = []
        y_weight = []
        y_energy = []
        
        for user in users_history:
            X = self.extract_temporal_features(user['eating_history'])
            if len(X) < 4:  # Need at least 4 weeks
                continue
            
            X_list.append(X[:-1])  # Use weeks 0-3 to predict week 4
            
            # Future BMI (week 4)
            y_bmi.append(user.get('future_bmi', user['current_bmi']))
            
            # Future weight (week 4)
            y_weight.append(user.get('future_weight', user['current_weight']))
            
            # Energy level (1-10 scale)
            y_energy.append(user.get('energy_level', 5))
        
        if X_list:
            X_train = np.vstack(X_list)
            self.bmi_model.fit(X_train, y_bmi)
            self.weight_model.fit(X_train, y_weight)
            self.energy_model.fit(X_train, y_energy)
            self.fitted = True
    
    def predict_health_outcome(self, recent_eating_history: list[dict]) -> dict:
        """Predict future health metrics."""
        if not self.fitted:
            return {"error": "Model not trained"}
        
        X = self.extract_temporal_features(recent_eating_history)
        
        if len(X) == 0:
            return {"error": "Insufficient data"}
        
        # Use last week as input
        X_recent = X[-1:, :]
        
        predicted_bmi = float(self.bmi_model.predict(X_recent)[0])
        predicted_weight = float(self.weight_model.predict(X_recent)[0])
        predicted_energy = float(self.energy_model.predict(X_recent)[0])
        
        return {
            "predicted_bmi": max(15.0, min(40.0, predicted_bmi)),  # Clamp to realistic range
            "predicted_weight_kg": max(40.0, min(200.0, predicted_weight)),
            "predicted_energy_level": max(1, min(10, predicted_energy)),
            "confidence": 0.75,  # Simple confidence estimate
            "recommendation": self._get_recommendation(predicted_bmi)
        }
    
    def _get_recommendation(self, predicted_bmi: float) -> str:
        """Provide actionable recommendation based on predicted BMI."""
        if predicted_bmi < 18.5:
            return "Tăng cách ăn cân bằng để đạt BMI tối ưu"
        elif predicted_bmi < 25:
            return "Duy trì chế độ ăn hiện tại - BMI tối ưu"
        elif predicted_bmi < 30:
            return "Giảm calories nhẹ và tăng tập luyện"
        else:
            return "Cần can thiệp dinh dưỡng bác sĩ"
```

**Timeline:** Day 17-20 | Output: `backend/ml/regression/health_predictor.py`

---

#### **5.7 Integration Layer** (Week 4-5)

**5.7.1 ML Pipeline Orchestrator**
```python
# backend/ml/pipeline_orchestrator.py
from backend.ml.nlp.intent_engine import IntentEngine
from backend.ml.clustering.user_segmentation import UserSegmentation
from backend.ml.recsys.knn_recommender import KNNRecommender
from backend.ml.optimization.csp_solver import MealPlanCSP
from backend.ml.regression.health_predictor import HealthOutcomePredictor

class MLPipeline:
    """Orchestrate all 5 ML modules in a coherent workflow."""
    
    def __init__(self):
        self.intent_engine = IntentEngine()
        self.user_segmentation = UserSegmentation(n_clusters=5)
        self.recommender = KNNRecommender(n_neighbors=5)
        self.health_predictor = HealthOutcomePredictor()
    
    def process_user_request(self, user_id: int, query: str, 
                            user_profile: dict) -> dict:
        """
        End-to-end ML pipeline.
        
        1. NLP: Extract intent + entities
        2. K-Means: Segment user
        3. KNN: Get food recommendations
        4. CSP: Generate meal plan
        5. Regression: Predict outcomes
        """
        
        # Step 1: NLP Intent Recognition
        intent_result = self.intent_engine.predict_intent(query)
        entities = self.intent_engine.extract_entities(query)
        
        # Step 2: User Segmentation
        segment_result = self.user_segmentation.predict_cluster(user_profile)
        
        # Step 3: KNN Recommendations
        similar_foods = self.recommender.recommend_by_constraint(
            target_nutrients=entities.get('target_nutrients', {}),
            exclude_foods=user_profile.get('excluded_foods', []),
            n=10
        )
        
        # Step 4: CSP Meal Planning
        csp = MealPlanCSP(user_profile, similar_foods)
        meal_plan = csp.solve(time_limit_sec=30)
        
        # Step 5: Health Prediction
        health_outcome = self.health_predictor.predict_health_outcome(
            user_profile.get('recent_eating_history', [])
        )
        
        return {
            "user_id": user_id,
            "intent": intent_result,
            "segment": segment_result,
            "recommendations": similar_foods,
            "meal_plan": meal_plan,
            "health_prediction": health_outcome,
            "timestamp": datetime.now().isoformat()
        }
```

**5.7.2 FastAPI Integration**
```python
# backend/app/routes/ml_routes.py
from fastapi import APIRouter, HTTPException
from backend.ml.pipeline_orchestrator import MLPipeline

router = APIRouter(prefix="/ml", tags=["ml"])
pipeline = MLPipeline()

@router.post("/meal-plan")
async def generate_meal_plan(
    user_id: int,
    query: str,
    user_profile: dict
):
    """Generate personalized 7-day meal plan with health prediction."""
    try:
        result = pipeline.process_user_request(user_id, query, user_profile)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health-prediction/{user_id}")
async def predict_health(user_id: int):
    """Get health outcome prediction for user."""
    # Fetch user history from DB
    # ...
    return pipeline.health_predictor.predict_health_outcome(history)
```

**Timeline:** Day 21-23 | Output: `backend/ml/pipeline_orchestrator.py`

---

#### **5.8 Testing & Validation** (Week 5)

```python
# tests/ml/test_intent_engine.py
def test_intent_recognition():
    engine = IntentEngine()
    engine.train(TRAINING_DATA)
    
    result = engine.predict_intent("Gợi ý bữa cơm để giảm 2kg trong 1 tháng")
    assert result["intent"] == "weight_loss_goal"
    assert result["confidence"] > 0.8

# tests/ml/test_csp_solver.py
def test_meal_plan_feasibility():
    user = {...}
    foods = [...]
    csp = MealPlanCSP(user, foods)
    result = csp.solve()
    
    assert result["feasible"] == True
    assert len(result["meal_plan"]) == 7

# tests/ml/test_knn_recommender.py
def test_knn_similarity():
    rec = KNNRecommender()
    rec.fit(vectors, metadata)
    
    recommendations = rec.recommend(food_id=1, n=5)
    assert len(recommendations) == 5
    assert all(0 <= r["similarity_score"] <= 1 for r in recommendations)
```

**Timeline:** Day 24-25 | Output: `tests/ml/`

---

#### **5.9 Deployment & Monitoring** (Week 5-6)

```dockerfile
# Dockerfile.ml
FROM python:3.11-slim

WORKDIR /app
COPY requirements-ml.txt .
RUN pip install -r requirements-ml.txt

COPY backend/ backend/
COPY data/ data/

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml (add ML service)
services:
  postgres:
    ...
  pgadmin:
    ...
  ai-backend:
    ...
  ml-service:
    build:
      context: .
      dockerfile: Dockerfile.ml
    environment:
      DATABASE_URL: postgresql://...
    ports:
      - "8001:8000"
    depends_on:
      - postgres
```

**Timeline:** Day 26-27 | Output: Docker ML service

---

#### **5.10 Timeline Summary**

| Week | Component | Status | Deliverable |
|------|-----------|--------|------------|
| 1 | Feature Store | ✅ | Feature extraction + caching |
| 2 | NLP Engine | ✅ | Intent recognition + entity extraction |
| 2-3 | K-Means Clustering | ✅ | User segmentation engine |
| 3 | KNN RecSys | ✅ | Food recommendation system |
| 3-4 | CSP Optimizer | ✅ | 7-day meal planner |
| 4 | Regression | ✅ | Health outcome predictor |
| 4-5 | Integration | ✅ | ML pipeline orchestrator |
| 5 | Testing | ✅ | 30+ ML tests |
| 5-6 | Deployment | ✅ | Docker + monitoring |

**Total Timeline:** 5-6 weeks (42-43 days)

---

#### **5.11 Dependencies & Data Flow**

```
Raw Data (9609 foods)
    ↓ (Feature Store)
    ↓ [Normalize nutrients]
    ↓
Nutrient Vectors (9609 × 14)
    ├─ → [NLP Engine]
    │      [Extract intent from user query]
    │      ↓
    │      [User Intent]
    │
    ├─ → [K-Means]
    │      [Cluster users]
    │      ↓
    │      [User Segment] 
    │
    ├─ → [KNN RecSys]
    │      [Find similar foods]
    │      ↓
    │      [Food Recommendations]
    │
    ├─ → [CSP Solver]
    │      [Solve with constraints]
    │      ↓
    │      [Meal Plan (28 meals)]
    │
    └─ → [Regression]
           [Predict health outcomes]
           ↓
           [Health Predictions + Recommendations]
```

---

#### **5.12 Resource Requirements**

| Component | RAM | CPU | Storage |
|-----------|-----|-----|---------|
| Feature Store (cache) | 500 MB | - | 2 GB |
| NLP Engine (models) | 300 MB | 1 core | 500 MB |
| K-Means (model) | 50 MB | 1 core | 100 MB |
| KNN (vectors) | 1 GB | 1 core | 1.5 GB |
| CSP Solver | 100 MB | 2 cores | - |
| Regression (models) | 50 MB | 1 core | 100 MB |
| **Total** | **~2.5 GB** | **4-6 cores** | **~5 GB** |

---

**Status:** 🎯 **PLAN READY** | Ready for Pha 5 execution

**Execution Start:** After Pha 4 CI/CD complete (Week 7)

---

### 📱 **Pha 6: Frontend & Deployment** (0% - FUTURE)

**Mục tiêu:** Giao diện người dùng và triển khai production.

#### 6.1 Frontend (React/Vue)
- User registration + profile
- Food search UI (autocomplete)
- Weekly meal plan viewer
- Nutrition summary dashboard
- Allergy manager

#### 6.2 Deployment
- Docker image: `nutriadvisor:v1.1.0`
- Kubernetes config (optional)
- PostgreSQL managed service (AWS RDS / Cloud SQL)
- API gateway (Kong / AWS API Gateway)
- Monitoring: Prometheus + Grafana

**Timeline:** 6-8 tuần

---

## III. Chi Tiết Từng Pha (Hướng Dẫn Cụ Thể)

### Pha 3: Test & Validation (CHI TIẾT)

#### Step 3.1: Thiết lập pytest
```bash
# Cài đặt
pip install pytest pytest-cov pytest-docker

# Tạo cấu trúc
mkdir -p tests/integration tests/unit
touch tests/__init__.py tests/conftest.py
```

#### Step 3.2: Viết unit tests
**File:** `tests/unit/test_load_structured_to_db.py`
```python
import pytest
from pathlib import Path
from data.scripts.load_structured_to_db import (
    _dedupe_rows_by_canonical_key,
    _clean_text,
    _to_float,
)

def test_dedupe_removes_duplicates():
    rows = [
        {"canonical_key": "beef", "name_en": "Beef A"},
        {"canonical_key": "beef", "name_en": "Beef B"},  # duplicate
        {"canonical_key": "chicken", "name_en": "Chicken"},
    ]
    result = _dedupe_rows_by_canonical_key(rows)
    assert len(result) == 2
    assert result[0]["name_en"] == "Beef A"  # first kept

def test_food_id_contiguous():
    # Mock: simulate 100 rows
    rows = [{"canonical_key": f"food_{i}"} for i in range(100)]
    deduped = _dedupe_rows_by_canonical_key(rows)
    assert len(deduped) == 100
    # Verify IDs would be 1→100 if inserted

def test_clean_text():
    assert _clean_text(None) == ""
    assert _clean_text("  hello  ") == "hello"
    assert _clean_text("NaN") == ""
```

#### Step 3.3: Viết integration tests
**File:** `tests/integration/test_api_search.py`
```python
import pytest
import psycopg
from fastapi.testclient import TestClient
from backend.app.main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def db_conn():
    url = "postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"
    with psycopg.connect(url) as conn:
        yield conn

def test_exact_match_returns_high_score(client, db_conn):
    response = client.get("/foods/search?q=beef%20noodle%20soup")
    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == "exact" or data["tier"] == "fuzzy"
    assert len(data["items"]) > 0
    assert "match_score" in data["items"][0]
    assert data["items"][0]["match_score"] > 0.5

def test_fuzzy_match_handles_typo(client):
    response = client.get("/foods/search?q=thitbo")  # typo: missing space
    assert response.status_code == 200
    data = response.json()
    assert data["tier"] in ["fuzzy", "fallback"]
```

#### Step 3.4: Chạy tests
```bash
pytest tests/ -v --cov=data.scripts --cov-report=html
```

**Timeline Pha 3:** 2-3 ngày

---

### Pha 4: CI/CD Pipeline (CHI TIẾT)

#### Step 4.1: Tạo GitHub Actions workflow
**File:** `.github/workflows/data-ci.yml`
```yaml
name: Data CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:13
        env:
          POSTGRES_USER: nutri_user
          POSTGRES_PASSWORD: minhdt
          POSTGRES_DB: nutri_advisor
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt
      
      - name: Lint with flake8
        run: flake8 data/scripts backend/app
      
      - name: Run migrations
        env:
          DATABASE_URL: postgresql://nutri_user:minhdt@localhost:5432/nutri_advisor
        run: python data/scripts/run_migrations.py --database-url "$DATABASE_URL"
      
      - name: Run unit tests
        run: pytest tests/unit -v
      
      - name: Load sample data
        env:
          DATABASE_URL: postgresql://nutri_user:minhdt@localhost:5432/nutri_advisor
        run: |
          python data/scripts/load_structured_to_db.py --version-tag v1.1.0 --reset
      
      - name: Run integration tests
        env:
          DATABASE_URL: postgresql://nutri_user:minhdt@localhost:5432/nutri_advisor
        run: pytest tests/integration -v
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

#### Step 4.2: Tạo requirements-test.txt
```
pytest==7.4.0
pytest-cov==4.1.0
pytest-docker==1.0.1
httpx==0.24.0
```

**Timeline Pha 4:** 2 ngày

---

### Pha 5: ML/CSP Ecosystem (CHI TIẾT - 5 Modules)

#### Step 5.1: Chuẩn bị dữ liệu training
```python
# data/scripts/prepare_features.py
import pandas as pd
import psycopg

def extract_nutrient_vectors():
    """Extract 14D feature vectors từ DB."""
    conn = psycopg.connect(...)
    df = pd.read_sql("""
        SELECT food_id, energy_kcal, protein_g, fat_g, carbs_g,
               vitamin_a_mcg, vitamin_c_mg, calcium_mg, iron_mg, ...
        FROM food_nutrients
    """, conn)
    return df  # 9609 x 14 matrix
```

#### Step 5.2: Xây dựng CSP solver
```python
# backend/ml/csp_solver.py
from constraint import Problem, AllDifferentConstraint

class MealPlanCSP:
    def __init__(self, user_profile, daily_calorie_target):
        self.problem = Problem()
        # 28 variables (7 days × 4 meals)
        # Domain: list of 9609 foods
        # Constraints: calorie sum, macro ratio, diversity, allergies
    
    def solve(self):
        """Return 7-day meal plan."""
        return self.problem.getSolution()
```

**Timeline Pha 5:** 4-6 tuần

---

### Pha 6: Frontend & Deployment (CHI TIẾT - Tóm tắt)

#### Step 6.1: Frontend React boilerplate
```bash
npx create-react-app frontend
cd frontend
npm install axios react-router-dom
```

#### Step 6.2: Docker production build
```dockerfile
# Dockerfile.prod
FROM python:3.11-slim as api-builder
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Step 6.3: Kubernetes manifest (optional)
```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nutriadvisor-api
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: api
        image: nutriadvisor:v1.1.0
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
```

**Timeline Pha 6:** 6-8 tuần

---

## IV. Lộ Trình Tổng Hợp

| Pha | Tên | Trạng Thái | Timeline | Key Artifact |
|-----|-----|-----------|----------|--------------|
| 1 | ETL & Data | ✅ HOÀN | - | `food_source_rows` (9934) + `foods` (9609) |
| 2 | Backend Search | ✅ HOÀN | - | `/foods/search` API |
| 3 | Test & Validation | ✅ HOÀN THÀNH | 2-3 ngày | pytest suite (49 tests) |
| 4 | CI/CD Pipeline | ✅ HOÀN THÀNH | 2 ngày | `.github/workflows/data-ci.yml` |
| 5 | ML Ecosystem (5 modules) | ⏳ FUTURE | 5-6 tuần | `backend/ml/` (NLP, K-Means, KNN, CSP, Regression) |
| 6 | Frontend & Deploy | ⏳ FUTURE | 6-8 tuần | React SPA + Kubernetes manifests |

**Pha 5 Chi Tiết (5 ML Modules):**

| Module | Week | Deliverable | Key Files |
|--------|------|-------------|-----------|
| **1. Feature Store** | 1 | ✅ HOÀN THÀNH: Nutrient vectors (9609×14) | `feature_store/extract_features.py` |
| **2. NLP Engine** | 1-2 | Intent recognition + entity extraction | `nlp/intent_engine.py` |
| **3. K-Means Clustering** | 2-3 | User segmentation into 5 groups | `clustering/user_segmentation.py` |
| **4. KNN RecSys** | 3 | Food recommendations by similarity | `recsys/knn_recommender.py` |
| **5. CSP Optimizer** | 3-4 | 7-day meal planner with constraints | `optimization/csp_solver.py` |
| **6. Linear Regression** | 4 | Health outcome prediction | `regression/health_predictor.py` |
| **7. Pipeline Integration** | 4-5 | Orchestrator + API routes | `pipeline_orchestrator.py` |
| **8. Testing & Deployment** | 5-6 | 30+ tests + Docker + monitoring | `tests/ml/` + `Dockerfile.ml` |

---

## V. Hướng Dẫn Chạy Nhanh (Quick Start)

### Lần đầu tiên
```bash
# 1. Setup
git clone <repo>
cd NutriAdvisor_HUST
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Docker
docker compose up -d --build

# 3. Migrations
$env:DATABASE_URL = "postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"
python data/scripts/run_migrations.py --baseline --database-url "$env:DATABASE_URL"

# 4. Load data (reset)
python data/scripts/load_structured_to_db.py --version-tag v1.1.0 --reset

# 5. Test API
curl "http://127.0.0.1:8000/foods/search?q=thit+bo"
```

### Lần tiếp theo (reload)
```bash
# Reset + reload (xóa hết, nạp lại từ CSV)
python data/scripts/load_structured_to_db.py --version-tag v1.1.0 --reset

# Hoặc chỉ insert mới (giữ dữ liệu cũ, thêm versions mới)
python data/scripts/load_structured_to_db.py --version-tag v1.2.0
```

---

## VI. KPI & Success Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Dữ liệu raw preserved | 100% | 9934 rows | ✅ |
| Canonical dedup | 9609 foods | 9609 | ✅ |
| Food ID contiguity | 1→9609 | 1→9609 | ✅ |
| API response time | <500ms | ~150ms | ✅ |
| Search recall (fuzzy) | >80% | To measure | 🔄 |
| Test coverage | >80% | 0% | ⏳ |
| CI/CD uptime | 99% | N/A | ⏳ |

---

## VII. Risks & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| CSV encoding issues | Medium | Low | UTF-8-sig BOM handling in loader |
| Migration checksum mismatch | Low | Medium | Never edit applied migrations; create new ones |
| Data quality (outliers) | Medium | Medium | Validation SQL queries; flag confidence_score < 0.7 |
| Scale (>100k foods) | Low | High | Partition food_source_rows by dataset_version_id |
| Model bias (NIN vs Kaggle) | Medium | High | Stratified sampling in training; monitor by source |

---

## VIII. Next Immediate Steps

### **Pha 3 (ĐÃ HOÀN THÀNH ✅)**
1. ✅ **Ngày 1-2:** Thiết lập pytest + viết 23 unit tests
2. ✅ **Ngày 2-3:** Viết 26 integration tests (DB schema + integrity)
3. ✅ **Pha 3:** 49 passing tests (unit + integration + API)
4. ✅ **Pha 4:** GitHub Actions CI/CD Pipeline complete

1. **Ngay bây giờ - Pha 4 Complete ✅:** GitHub Actions CI/CD Pipeline deployed
   - Workflow file: `.github/workflows/data-ci.yml` 
   - Linting, unit tests, integration tests, smoke tests, coverage tracking
   - Ready for push to GitHub

2. **Next - Pha 5 Start (Week 7+):** ML Ecosystem (5-6 weeks)
   - Module 1: Feature Store (Week 1)
   - Module 2: NLP Engine with Hybrid approach (Week 1-2)
   - Modules 3-5: K-Means, KNN, CSP (Week 2-4)
   - Module 6: Regression (Week 4)
   - Integration & Testing (Week 5-6)

**Status:** 49/49 tests passing | Ready for Pha 4

---

### **Pha 4 (Tuần tới - 2 ngày)**

1. **Ngày 1:** Tạo GitHub Actions workflow (`.github/workflows/data-ci.yml`)
   - Linting (flake8, black)
   - Unit tests + integration tests
   - Coverage reporting
   - Migration verification

2. **Ngày 2:** Validate CI/CD locally
   - Run full workflow
   - Check coverage > 80%
   - Deploy mock release

**Start:** After Pha 3 complete → ✅ NOW COMPLETE

---

### **Pha 5 (Tuần 7+ - 5-6 tuần)**

**Timeline chi tiết (5 ML modules):**
- Week 1: Feature Store extraction + normalization
- Week 1-2: NLP Intent Engine
- Week 2-3: K-Means User Segmentation
- Week 3: KNN Recommendation System
- Week 3-4: CSP Meal Planner
- Week 4: Linear Regression Health Predictor
- Week 4-5: Pipeline Integration + API routes
- Week 5-6: Testing, deployment, monitoring

**Structure:** See [Section 5](#5-module-ml-ecosystem) for complete architecture

---

**Liên hệ:** Review plan này với team trước khi proceed Pha 4.

