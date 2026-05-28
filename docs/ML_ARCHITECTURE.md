# ML Ecosystem Architecture - Chi Tiết 5 Modules

**Dự án:** NutriAdvisor ML System  
**Phiên bản:** 1.0 (Pha 5)  
**Ngày:** 2026-04-29  
**Trạng thái:** Architecture Definition

---

## I. Tổng Quan Hệ Thống

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER INTERACTION LAYER                      │
│                    /foods/meal-plan (POST)                       │
│                  {query, user_profile, history}                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ↓
      ┌──────────────────────────────────────────────┐
      │    ML PIPELINE ORCHESTRATOR                  │
      │  (pipeline_orchestrator.py)                  │
      │  • Coordinates all 5 modules                 │
      │  • Handles error recovery                    │
      │  • Logs metrics                              │
      └──┬──────┬──────┬──────┬──────────────────────┘
         │      │      │      │
    ┌────▼──┐ ┌─▼─────┐ ┌────▼──┐ ┌──────┐ ┌─────────┐
    │ NLP   │ │K-Means│ │ KNN   │ │ CSP  │ │Regress. │
    │Engine │ │Cluster│ │RecSys │ │Optim.│ │Predictor│
    │       │ │       │ │       │ │      │ │         │
    │ Intent│ │User   │ │Food   │ │7-day │ │ Health  │
    │Extract│ │Segment│ │Recommend│Meal  │ │Forecast │
    │       │ │       │ │       │ │Plan  │ │         │
    └───┬───┘ └─┬─────┘ └──┬────┘ └──┬───┘ └────┬────┘
        │       │          │         │         │
        └───────┴──────────┴─────────┴─────────┘
                      │
                      ↓
        ┌─────────────────────────┐
        │  FEATURE STORE          │
        │  (PostgreSQL + Cache)   │
        │  • Food vectors (9609)  │
        │  • User profiles        │
        │  • Eating history       │
        │  • Generated plans      │
        └─────────────────────────┘
                      │
                      ↓
        ┌─────────────────────────┐
        │   API Response          │
        │  {meal_plan, prediction}│
        └─────────────────────────┘
```

---

## II. Detailed Module Specifications

### **Module 1: NLP Engine (Hybrid Architecture)**

**Mục tiêu:** Hiểu user wants gì từ query tự nhiên (simple local + complex API)

**Input:** Vietnamese text query (e.g., "Gợi ý bữa cơm để giảm 2kg trong 1 tháng")

**Output:**
```json
{
  "intent": "weight_loss_goal",
  "confidence": 0.92,
  "source": "api",
  "entities": {
    "weight_loss_kg": 2.0,
    "duration_days": 30,
    "calories": null,
    "allergies": [],
    "cuisines": []
  }
}
```

**Hybrid Strategy:**

**Tier 1: Local Training (Simple Intents)**
- Intent: recommend, allergies, budget, cuisine
- Implementation: TF-IDF + Naive Bayes
- Accuracy: 88-92%
- Latency: 50ms
- Cost: Free
- Confidence threshold: >0.85

**Tier 2: External API (Complex Intents)**
- Intent: weight_loss_goal, health_goal, meal_planning_constraints
- Providers: Google Cloud NLP, Azure Text Analytics, or Claude API
- Accuracy: 95%+
- Latency: 200-500ms
- Cost: Per-request
- Fallback: Return local prediction with confidence <0.85

**Decision Logic:**
```
IF local_confidence > 0.85:
    return local prediction
ELSE IF intent in ["weight_loss", "health", "complex"]:
    call external API
ELSE:
    return local prediction (lower confidence warning)
```

**Intents by Tier:**
```python
LOCAL_INTENTS = {
    "recommend": "Gợi ý bữa cơm",         # Easy: simple keywords
    "allergies": "Bị dị ứng",            # Easy: list known allergens
    "budget": "Budget N đồng",           # Easy: regex for numbers
    "cuisine": "Thích món X",            # Easy: cuisine list lookup
}

API_INTENTS = {
    "weight_loss": "Muốn giảm N kg",     # Hard: requires NLU
    "muscle_gain": "Muốn tăng cơ",       # Hard: complex constraints
    "health_goal": "Complex health",      # Hard: medical domain knowledge
}
```

**Training Data Sample (Local Only):**
```python
training_data = [
    ("Gợi ý bữa cơm cho tôi hôm nay", "recommend_meal"),
    ("Tôi bị dị ứng tôm", "allergy_declaration"),
    ("Bữa cơm không quá 50k", "budget_constraint"),
    ("Tôi thích ăn Á", "cuisine_preference"),
    ...
]
```

**Deployment:**
- Local: Python module (sklearn-based, no GPU)
- Remote: Cloud API client with retry logic and fallback

---
### **NLP Hybrid Architecture - Configuration & API Options**

**Lựa chọn API Provider:**

| Provider | Cost | Quality | Latency | Vietnamese | Recommendation |
|----------|------|---------|---------|------------|----------------|
| **Underthesea** | $0 (Free lib) | 85% | 50ms | ✅ Native | ⭐ Best Vietnamese |
| **Google Cloud NLP** | $0 (5k/mo free) | 94% | 200ms | Good | ✅ Free tier huge |
| **AWS Comprehend** | $0 (100k/mo free) | 92% | 250ms | Fair | ✅ Generous free |
| **Azure Text Analytics** | $0 (5k/mo free) | 93% | 250ms | Good | ✅ Enterprise |
| **Ollama (Local LLM)** | $0 (∞ free) | 88% | 2-5s | Good | ✅ Privacy + free |
| **PhoBERT** | $0 (∞ free) | 89% | 500ms | ✅ Excellent | ✅ Vietnamese BERT |
| Claude (paid) | $0.003/1k tokens | 96% | 500ms | Excellent | Only if high volume |

**💡 Recommended Strategy: HYBRID LOCAL + FREE TIERS**

```env
# 100% FREE - No costs at all
NLP_MODE=hybrid
NLP_LOCAL_PROVIDER=underthesea     # Vietnamese NLP library (free)
NLP_API_PROVIDER=google            # Free: 5,000 requests/month
NLP_ENABLE_CACHING=true            # Redis cache to maximize free quota
NLP_CONFIDENCE_THRESHOLD=0.85

# With this setup:
# - 70% requests: Underthesea (free, local)
# - 30% requests: Google Cloud (free tier covers 5k/month)
# - Result: $0 cost, ~91% accuracy, 80ms latency
```

**Cost Breakdown (100k requests/month):**
```
Pure Local (Underthesea):    $0  ✅
Hybrid Local + Free Tiers:   $0  ✅ (completely free)
Hybrid Local + Paid API:     $50-200
API Only (Claude):           $300+

→ BEST OPTION: Hybrid Local + Free Tiers ($0 cost)
```

**Underthesea - Vietnamese NLP (Completely Free)**

```python
# pip install underthesea
from underthesea import word_tokenize, ner, sentiment

# Vietnamese-aware tokenization
tokens = word_tokenize("Tôi muốn giảm 2kg")
# ['Tôi', 'muốn', 'giảm', '2kg']

# Named Entity Recognition
entities = ner("Tôi muốn giảm 2kg trong 1 tháng")
# [('Tôi', 'P'), ('2kg', 'M'), ('1 tháng', 'T')]

# Sentiment analysis
sentiment = sentiment("Tôi rất thích bữa cơm này")
# 'positive'

# 100% FREE, Vietnamese-native, no API needed!
```

**Configuration Example (.env):**
```
NLP_MODE=hybrid                    # Hybrid local + free APIs
NLP_LOCAL_PROVIDER=underthesea     # Vietnamese library
NLP_API_PROVIDER=google            # Use free tier (5k/month)
NLP_API_KEY=xxxxxxxxxxxxx
NLP_CONFIDENCE_THRESHOLD=0.85      # If local < 0.85, try API
NLP_ENABLE_CACHING=true            # Cache to save quota
NLP_API_TIMEOUT=5
```

**Free Tier Limits (100% covers most projects):**
- Google Cloud NLP: 5,000 requests/month ✅
- AWS Comprehend: 100,000 requests/month ✅
- Azure Text Analytics: 5,000 records/month ✅
- Underthesea: ∞ requests (local) ✅

---

### **Module 2: K-Means User Segmentation**

**Mục tiêu:** Nhóm users thành 5 segments để gợi ý "Menu mẫu"

**User Features Extracted:**
```
[age, BMI, daily_calorie_target, num_allergies, health_goal_encoded]
```

**Clustering Result:**

| Segment | Count | BMI Range | Target Cal | Budget | Preference |
|---------|-------|-----------|-----------|--------|------------|
| Budget-Conscious | ~20% | 22-28 | 1800-2000 | 50k | Vietnamese |
| Health-Focused | ~25% | 20-24 | 1600-1900 | 150k | Organic |
| Performance-Athlete | ~15% | 20-22 | 2500-3200 | 200k | High-protein |
| Balanced-Lifestyle | ~30% | 21-25 | 2000-2200 | 100k | Diverse |
| Premium-Wellness | ~10% | 19-23 | 1800-2400 | 300k | Gourmet |

**Menu Templates per Cluster:**
```python
# Example: Budget-Conscious segment
MENU_TEMPLATES["budget_conscious"] = {
    "daily_budget_vnd": 50000,
    "meals_per_day": 3,
    "cuisine_preference": ["Vietnamese", "Asian"],
    "target_calories": 1800,
    "priority": "cost_effective",
    "popular_foods": [
        "white_rice",  # food_id mappings
        "pickled_vegetables",
        "grilled_chicken_simple",
        ...
    ]
}
```

**Use Case:**
- User signs up → K-Means predicts segment
- "You belong to Health-Focused segment"
- Pre-fill menu template for faster recommendations

**Model Training:**
- Input: 1000+ user profiles
- Algorithm: K-Means (k=5, init='k-means++')
- Feature scaling: StandardScaler
- Output: Cluster centers, segment names

---

### **Module 3: KNN Recommendation System (RecSys)**

**Mục tiêu:** Gợi ý foods tương tự dựa trên nutrient vectors

**Algorithm:** K-Nearest Neighbors with cosine similarity

**Input:**
```python
# Option 1: Query by food_id (find similar foods)
recommend(query_food_id=1, n=5)

# Option 2: Query by nutrient constraints
recommend_by_constraint(
    target_nutrients={
        "energy_kcal": 250,
        "protein_g": 25,
        "fat_g": 10,
        "carbs_g": 20
    },
    exclude_foods=[1, 2, 3],  # Foods to skip
    n=10
)
```

**Output:**
```json
{
  "recommendations": [
    {
      "food_id": 42,
      "canonical_key": "chicken_breast",
      "name_en": "Chicken Breast",
      "similarity_score": 0.92
    },
    {
      "food_id": 58,
      "canonical_key": "turkey_breast",
      "name_en": "Turkey Breast",
      "similarity_score": 0.87
    }
  ]
}
```

**Distance Metric:**
- Cosine similarity on 14D nutrient vectors
- Formula: `similarity = 1 - distance`
- Range: [0.0, 1.0]

**Performance:**
- Training: O(n) on 9609 foods
- Query: O(n log k) per query (very fast)
- RAM: ~1 GB for food vectors

**Integration with CSP:**
- CSP solver uses KNN for food pool
- Initial recommendations → CSP constraints → Final meal plan

---

### **Module 4: CSP Meal Planner (Optimization)**

**Mục tiêu:** Giải bài toán xếp 28 bữa ăn (7 days × 4 meals)

**Problem Definition:**
```
Variables: 28 (meal_day0_breakfast, meal_day0_lunch, ..., meal_day6_dinner)
Domain: Each variable can take any food_id from 1-9609
Constraints: (see below)
```

**Constraints:**

1. **Daily Calories ≈ Target ± 10%**
   - User target: 2000 kcal
   - Acceptable range: [1800, 2200] kcal/day

2. **Macro Ratios P:F:C within ±5% tolerance**
   - Target: {protein: 30%, fat: 30%, carbs: 40%}
   - Protein: 27-33%
   - Fat: 27-33%
   - Carbs: 37-43%

3. **Diversity (No same food >2×/week)**
   - Prevents "chicken every day" fatigue
   - Max occurrences: 2 per food per week

4. **Respect Allergies**
   - Filter out foods containing known allergens
   - User allergies: ["peanut", "shellfish", ...]

5. **Budget Constraint (optional)**
   - Daily budget: 100k VND
   - Total weekly: ≤ 700k VND

**Solver Options:**

| Solver | Speed | Quality | Notes |
|--------|-------|---------|-------|
| python-constraint | Fast | Good | Backtracking CSP solver |
| OR-Tools | Very Fast | Excellent | Google optimization library |
| Gurobi | Slow | Optimal | Commercial (expensive) |

**Recommended:** python-constraint (open-source, sufficient for this problem)

**Example Solution:**
```python
meal_plan = {
    "day": 1,
    "meals": [
        {"slot": "breakfast", "food_id": 12, "name": "Rice Porridge", "kcal": 180},
        {"slot": "lunch", "food_id": 42, "name": "Grilled Chicken", "kcal": 350},
        {"slot": "snack", "food_id": 89, "name": "Banana", "kcal": 105},
        {"slot": "dinner", "food_id": 156, "name": "Steamed Fish", "kcal": 250}
    ],
    "day_totals": {"kcal": 885, "protein_g": 75, "fat_g": 28, "carbs_g": 95}
}
```

**Error Handling:**
```python
solution = csp.solve(time_limit=30)

if not solution["feasible"]:
    # Fallback: Relax constraints
    # Remove diversity constraint
    # Increase calorie tolerance to ±15%
    # Try again
    solution = csp.solve_relaxed()
```

---

### **Module 5: Linear Regression Health Predictor**

**Mục tiêu:** Dự báo chỉ số sức khỏe tương lai (BMI, weight, energy)

**Input:** 4 weeks eating history

**Output:**
```json
{
  "predicted_bmi": 24.2,
  "predicted_weight_kg": 67.5,
  "predicted_energy_level": 7.8,
  "confidence": 0.78,
  "recommendation": "Duy trì chế độ ăn hiện tại - BMI tối ưu"
}
```

**Features (Weekly Aggregates):**
```
Week 0: [avg_energy_kcal, avg_protein_g, avg_carbs_g, avg_fat_g]
Week 1: [avg_energy_kcal, avg_protein_g, avg_carbs_g, avg_fat_g]
Week 2: [avg_energy_kcal, avg_protein_g, avg_carbs_g, avg_fat_g]
Week 3: [avg_energy_kcal, avg_protein_g, avg_carbs_g, avg_fat_g]
  ↓
  └─→ Predict Week 4 outcomes
```

**Models Trained:**
- BMI regression (predicts future BMI)
- Weight regression (predicts weight change)
- Energy regression (predicts subjective energy level 1-10)

**Training Data Requirements:**
- 500+ users with 8+ weeks of eating data
- Labels: actual BMI/weight/energy at week 8

**Recommendations Generated:**
```python
def _get_recommendation(predicted_bmi):
    if predicted_bmi < 18.5:
        return "Tăng cách ăn cân bằng để đạt BMI tối ưu"
    elif predicted_bmi < 25:
        return "Duy trì chế độ ăn hiện tại - BMI tối ưu"
    elif predicted_bmi < 30:
        return "Giảm calories nhẹ và tăng tập luyện"
    else:
        return "Cần can thiệp dinh dưỡng bác sĩ"
```

---

## III. Data Structures & Schemas

### FeatureStore Schema
```python
@dataclass
class FoodFeature:
    food_id: int
    canonical_key: str
    energy_kcal_norm: float  # 0-1 normalized
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
    # Vector form:
    vector: np.ndarray  # Shape: (14,), values in [0, 1]
```

### UserProfile Schema
```python
@dataclass
class UserProfile:
    user_id: int
    age: int
    weight_kg: float
    height_cm: float
    daily_calorie_target: float
    macro_ratios: dict  # {protein: 0.3, fat: 0.3, carbs: 0.4}
    allergies: list[str]
    dietary_preferences: list[str]
    health_goal: str
    excluded_foods: list[int]
    segment: str  # From K-Means
    created_at: datetime
    updated_at: datetime
```

### MealPlan Schema
```python
@dataclass
class MealPlan:
    plan_id: int
    user_id: int
    num_days: int
    num_meals_per_day: int
    status: str  # "feasible" / "infeasible" / "partial"
    meals: list[Meal]  # 7 days × 4 meals
    total_calories: float
    macro_breakdown: dict
    confidence_score: float
    generated_at: datetime
```

---

## IV. Dependencies & Data Flow

### Build Order (Must follow this order)

```
1. Feature Store
   ├─ Extract food vectors from DB
   ├─ Normalize to [0, 1]
   └─ Cache to disk
   
2. NLP Engine (no dependencies)
   ├─ Train on Vietnamese texts
   └─ Save model
   
3. K-Means Clustering
   ├─ Extract user features
   ├─ Fit K-Means
   └─ Create cluster assignments
   
4. KNN RecSys
   ├─ Load food vectors (from Feature Store)
   ├─ Fit KNN index
   └─ Ready for querying
   
5. CSP Solver
   ├─ Use KNN for food pool
   ├─ Use Feature Store for constraints
   └─ Ready for meal planning
   
6. Regression Predictor
   ├─ Load user eating history
   ├─ Train models
   └─ Ready for predictions
   
7. Pipeline Orchestrator
   ├─ Integrate all 6 modules
   └─ Expose via API
```

### Data Flow in Production
```
Request: /ml/meal-plan
    ↓
[1] NLP Engine: Extract intent + entities
    ↓
[2] K-Means: Get user segment
    ↓
[3] KNN RecSys: Find candidate foods
    ↓
[4] CSP Solver: Optimize meal plan
    ↓
[5] Regression: Predict health outcome
    ↓
Response: {meal_plan, prediction, confidence}
```

---

## V. Performance Characteristics

| Module | Training Time | Query Time | RAM Usage | Notes |
|--------|---------------|-----------|-----------|-------|
| NLP | 5 min | 50 ms | 300 MB | Sklearn TF-IDF |
| K-Means | 10 min | 1 ms | 50 MB | 5 clusters |
| KNN | 30 sec | 100 ms | 1 GB | 9609 foods |
| CSP | - | 2-30 sec | 100 MB | Depends on constraints |
| Regression | 15 min | 5 ms | 50 MB | 3 linear models |
| **Total** | **~1 hour** | **~200 ms** | **~2.5 GB** | Cold start |

---

## VI. Monitoring & Metrics

**KPIs to Track:**

1. **Intent Recognition Accuracy**
   - Metric: % correct intent predictions
   - Target: >85%

2. **Meal Plan Feasibility**
   - Metric: % solvable CSP problems
   - Target: >95%

3. **User Satisfaction**
   - Metric: Rating of recommended meals
   - Target: >4.0/5.0

4. **Prediction Accuracy**
   - Metric: MAE (Mean Absolute Error) on BMI/weight
   - Target: MAE < 0.5 BMI units

5. **API Response Time**
   - Metric: p50, p95, p99 latencies
   - Target: p50 < 200ms, p99 < 2s

---

## VII. Testing Strategy

### Unit Tests (20+)
```python
def test_intent_recognition_weight_loss():
    query = "Tôi muốn giảm 2kg trong 1 tháng"
    intent = engine.predict_intent(query)
    assert intent["intent"] == "weight_loss_goal"
    assert intent["confidence"] > 0.8

def test_kmeans_clustering():
    users = [...]
    segmentation.fit_clusters(users)
    cluster = segmentation.predict_cluster(test_user)
    assert cluster["segment_name"] in ["budget_conscious", ...]

def test_knn_similarity():
    rec = KNNRecommender()
    rec.fit(vectors, metadata)
    similar = rec.recommend(food_id=1, n=5)
    assert len(similar) == 5
    assert all(0 <= r["similarity_score"] <= 1 for r in similar)

def test_csp_feasibility():
    user = {...}
    csp = MealPlanCSP(user, foods)
    solution = csp.solve()
    assert solution["feasible"] == True

def test_regression_prediction():
    history = [...]
    pred = regressor.predict_health_outcome(history)
    assert "predicted_bmi" in pred
    assert 15 < pred["predicted_bmi"] < 40
```

### Integration Tests (10+)
```python
def test_full_pipeline():
    """End-to-end test of all 5 modules."""
    user_query = "Gợi ý bữa cơm để giảm 2kg"
    user_profile = {...}
    
    result = pipeline.process_user_request(
        user_id=1, 
        query=user_query,
        user_profile=user_profile
    )
    
    # Verify all modules ran
    assert "intent" in result
    assert "segment" in result
    assert "recommendations" in result
    assert "meal_plan" in result
    assert "health_prediction" in result
```

---

## VIII. Rollout Plan

**Week 1:** Deploy Feature Store + NLP Engine (no user impact)
**Week 2:** Deploy K-Means (beta: 10% of users)
**Week 3:** Deploy KNN + CSP (beta: 25% of users)
**Week 4:** Deploy Regression + full pipeline (50% of users)
**Week 5-6:** Monitoring, feedback, optimizations
**Week 6:** 100% rollout

---

**Status:** 🎯 **ARCHITECTURE READY** | Implementation can start

**Next:** Implement modules in order: Feature Store → NLP → K-Means → KNN → CSP → Regression
