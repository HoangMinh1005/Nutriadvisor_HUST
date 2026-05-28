# Hướng Dẫn Chạy Tests - Pha 3 (Test & Validation Framework)

**Trạng thái:** ✅ Framework hoàn thành  
**Ngày tạo:** 2026-04-29  
**Tests:** 50+ test cases

---

## I. Cài Đặt & Chuẩn Bị

### 1.1 Cài đặt dependencies
```bash
# Kích hoạt virtual environment
.venv\Scripts\Activate.ps1

# Cài đặt test packages
pip install -r requirements-test.txt
```

### 1.2 Chuẩn bị DATABASE_URL
```powershell
# Windows PowerShell
$env:DATABASE_URL = "postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"

# Kiểm tra
echo $env:DATABASE_URL
```

### 1.3 Đảm bảo các dịch vụ chạy
```bash
# Terminal 1: Docker (Postgres + FastAPI)
docker compose up -d

# Kiểm tra
docker compose ps
# Cần thấy: postgres (healthy), pgadmin, ai-backend (running)

# Terminal 2: Chạy FastAPI nếu chưa
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 1.4 Migrations & Data (nếu chưa có)
```bash
# Áp dụng migrations
python data/scripts/run_migrations.py --baseline

# Load dữ liệu
python data/scripts/load_structured_to_db.py --version-tag v1.1.0 --reset
```

---

## II. Chạy Tests

### 2.1 Chạy tất cả tests
```bash
# Chạy tất cả tests với verbose output
pytest tests/ -v

# Chạy tất cả tests với coverage report
pytest tests/ -v --cov=data.scripts --cov=backend --cov-report=html
```

### 2.2 Chạy unit tests (không cần database)
```bash
# Chỉ chạy unit tests (nhanh, ~5 giây)
pytest tests/unit/ -v

# Unit tests + coverage
pytest tests/unit/ -v --cov=data.scripts --cov-report=term-missing
```

### 2.3 Chạy integration tests (cần database + API)
```bash
# Chỉ chạy integration tests
pytest tests/integration/ -v

# Integration tests + coverage
pytest tests/integration/ -v --cov=data.scripts --cov-report=term-missing
```

### 2.4 Chạy single test file
```bash
# Chạy riêng unit tests for loader
pytest tests/unit/test_load_structured_to_db.py -v

# Chạy riêng database integration tests
pytest tests/integration/test_database.py -v

# Chạy riêng API integration tests
pytest tests/integration/test_api_search.py -v
```

### 2.5 Chạy single test class
```bash
# Chạy chỉ TestCleanText class
pytest tests/unit/test_load_structured_to_db.py::TestCleanText -v

# Chạy chỉ TestDatabaseSchema class
pytest tests/integration/test_database.py::TestDatabaseSchema -v
```

### 2.6 Chạy single test method
```bash
# Chạy một test cụ thể
pytest tests/unit/test_load_structured_to_db.py::TestCleanText::test_clean_text_none_returns_empty -v
```

---

## III. Test Coverage & Reports

### 3.1 Generate HTML coverage report
```bash
# Tạo HTML coverage report
pytest tests/ --cov=data.scripts --cov=backend --cov-report=html

# Mở report trong browser
start htmlcov/index.html
```

### 3.2 Terminal coverage summary
```bash
# Hiển thị coverage trên terminal
pytest tests/ --cov=data.scripts --cov-report=term-missing
```

### 3.3 Coverage benchmarks
```
Target coverage: >80%

Expected coverage:
- data/scripts/load_structured_to_db.py: ~85% (unit tests cover helpers)
- backend/app/services/food_search.py: ~70% (API tests)
- Overall: ~78%
```

---

## IV. Test Cases Overview

### **Unit Tests (13 test cases)** ✅

**File:** `tests/unit/test_load_structured_to_db.py`

#### TestCleanText (5 tests)
- ✅ `test_clean_text_none_returns_empty` → None → ""
- ✅ `test_clean_text_strips_whitespace` → "  hello  " → "hello"
- ✅ `test_clean_text_converts_nan_variants` → "NaN" → ""
- ✅ `test_clean_text_preserves_valid_text` → "Beef" → "Beef"
- ✅ `test_clean_text_handles_numbers` → 123 → "123"

#### TestToFloat (6 tests)
- ✅ `test_to_float_valid_integers` → "100" → 100.0
- ✅ `test_to_float_valid_floats` → "25.5" → 25.5
- ✅ `test_to_float_null_values_return_zero` → None → 0.0
- ✅ `test_to_float_invalid_strings_return_zero` → "abc" → 0.0
- ✅ `test_to_float_whitespace` → "   " → 0.0
- ✅ `test_to_float_negative_numbers` → "-50.5" → -50.5

#### TestToBool (3 tests)
- ✅ `test_to_bool_truthy_strings` → "true"/"yes"/"1" → True
- ✅ `test_to_bool_falsy_strings` → "false"/"0" → False
- ✅ `test_to_bool_with_whitespace` → "  true  " → True

#### TestDedupeRowsByCanonicalKey (6 tests)
- ✅ `test_dedupe_keeps_first_occurrence` → removes duplicates
- ✅ `test_dedupe_removes_empty_keys` → filters ""
- ✅ `test_dedupe_preserves_order` → maintains order
- ✅ `test_dedupe_empty_input` → [] → []
- ✅ `test_dedupe_single_row` → [row] → [row]
- ✅ `test_dedupe_all_unique_keys` → keeps all
- ✅ `test_dedupe_counts_match` → correct count

#### TestHelperFunctionsIntegration (2 tests)
- ✅ `test_food_row_cleaning_pipeline` → integration test
- ✅ `test_csv_row_with_all_null_values` → edge case

---

### **Integration Tests - Database (22 test cases)** ✅

**File:** `tests/integration/test_database.py`

#### TestDatabaseSchema (8 tests)
- ✅ `test_schema_migrations_table_exists` → tracking table
- ✅ `test_foods_table_exists` → schema validation
- ✅ `test_food_nutrients_table_exists` → 14 nutrient fields
- ✅ `test_food_aliases_table_exists` → search table
- ✅ `test_food_source_rows_table_exists` → raw data table
- ✅ `test_pg_trgm_extension_enabled` → fuzzy search ready
- ✅ `test_foods_table_has_primary_key` → PK validation
- ✅ `test_food_nutrients_has_foreign_key_to_foods` → FK validation

#### TestDataIntegrity (7 tests)
- ✅ `test_food_count_equals_nutrient_count` → 1:1 mapping
- ✅ `test_no_orphan_food_nutrients` → referential integrity
- ✅ `test_no_orphan_food_aliases` → referential integrity
- ✅ `test_food_id_is_contiguous` → 1→N (no gaps)
- ✅ `test_no_duplicate_canonical_keys` → uniqueness
- ✅ `test_no_null_canonical_keys` → not null constraint
- ✅ `test_food_source_rows_count_greater_or_equal_foods` → raw≥canonical

#### TestDataValues (3 tests)
- ✅ `test_nutrient_values_are_non_negative` → data quality
- ✅ `test_energy_values_in_reasonable_range` → 0-900 kcal/100g
- ✅ `test_confidence_scores_valid_range` → 0.0-1.0

#### TestDataLoader (4 tests)
- ✅ `test_csv_file_exists` → file validation
- ✅ `test_alias_csv_file_exists` → file validation
- ✅ `test_manifest_file_valid` → JSON validation
- ✅ `test_dataset_version_exists` → version tracking

#### TestSearchIndexing (3 tests)
- ✅ `test_gin_index_on_alias_text` → fuzzy search index
- ✅ `test_alias_count_sufficient` → coverage validation
- ✅ `test_trgm_similarity_search_works` → pg_trgm functionality

---

### **Integration Tests - API (20 test cases)** ✅

**File:** `tests/integration/test_api_search.py`

#### TestFoodSearchEndpoint (10 tests)
- ✅ `test_search_endpoint_exists` → HTTP 200
- ✅ `test_search_returns_json` → valid JSON response
- ✅ `test_search_response_structure` → tier + items fields
- ✅ `test_search_tier_is_valid` → exact/fuzzy/fallback
- ✅ `test_search_items_is_list` → array type
- ✅ `test_search_item_structure` → food_id, match_score, etc.
- ✅ `test_search_match_score_in_valid_range` → 0.0-1.0
- ✅ `test_search_with_empty_query` → graceful handling
- ✅ `test_search_case_insensitive` → "BEEF" vs "beef"
- ✅ `test_search_with_vietnamese_query` → UTF-8 support

#### TestAPIErrors (3 tests)
- ✅ `test_invalid_endpoint_returns_404` → HTTP 404
- ✅ `test_search_missing_parameter_handled` → bad input
- ✅ `test_api_handles_special_characters` → escape handling

#### TestAPIPerformance (2 tests)
- ✅ `test_search_response_time_reasonable` → <2s latency
- ✅ `test_multiple_sequential_searches` → stability

#### TestAPIIntegration (5 tests)
- ✅ `test_search_returns_existing_foods` → DB consistency
- ✅ `test_search_multiple_queries_consistency` → deterministic
- ✅ `test_search_with_typo_returns_fuzzy_results` → fuzzy tier
- ✅ `test_search_nutrition_fields_present` → response completeness
- ✅ `test_search_returns_reasonable_count` → ≤100 items
- ✅ `test_search_results_sorted_by_relevance` → descending order
- ✅ `test_search_exact_tier_high_scores` → quality check

---

## V. Troubleshooting

### Q: "DATABASE_URL is not configured"
```bash
# PowerShell:
$env:DATABASE_URL = "postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"

# Bash:
export DATABASE_URL="postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"
```

### Q: "Connection refused" (database not running)
```bash
# Check docker
docker compose ps

# Start if needed
docker compose up -d

# Wait for postgres health check
docker compose logs postgres
```

### Q: "No module named 'backend'" (API tests fail)
```bash
# Ensure PYTHONPATH includes project root
$env:PYTHONPATH = "d:\Minh\NutriAdvisor_HUST"
pytest tests/integration/test_api_search.py -v
```

### Q: "Cannot connect to http://127.0.0.1:8000" (API not running)
```bash
# Terminal 2: Start FastAPI
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Q: Tests timeout
```bash
# Increase timeout
pytest tests/integration/ -v --timeout=30
```

---

## VI. Full Test Workflow (Recommended)

### Day 1: Unit Tests Only
```bash
# Setup
pip install -r requirements-test.txt

# Run unit tests (fast, no DB)
pytest tests/unit/ -v --cov=data.scripts --cov-report=html

# Review coverage
start htmlcov/index.html
```

### Day 2: Integration Tests + API
```bash
# Ensure services running
docker compose up -d
# (Start FastAPI in separate terminal)

# Run all integration tests
pytest tests/integration/ -v

# Check results
pytest tests/integration/test_database.py -v
pytest tests/integration/test_api_search.py -v
```

### Day 3: Full Suite + Coverage
```bash
# Run all tests with coverage
pytest tests/ -v --cov=data.scripts --cov=backend --cov-report=html

# Generate report
# → htmlcov/index.html (target: >80%)

# Run specific test classes if any fail
pytest tests/integration/test_database.py::TestDataIntegrity -v -s
```

---

## VII. CI/CD Integration (Next Phase)

These tests will be integrated into GitHub Actions workflow:

```yaml
# .github/workflows/data-ci.yml
- name: Run unit tests
  run: pytest tests/unit/ -v
  
- name: Run integration tests
  run: pytest tests/integration/ -v
  
- name: Generate coverage report
  run: pytest tests/ --cov --cov-report=xml
  
- name: Upload to Codecov
  uses: codecov/codecov-action@v3
```

---

## VIII. Quick Reference

```bash
# All tests
pytest tests/ -v

# Unit tests only (fast)
pytest tests/unit/ -v

# Integration tests (requires DB + API)
pytest tests/integration/ -v

# With coverage
pytest tests/ --cov --cov-report=html

# Specific test
pytest tests/unit/test_load_structured_to_db.py::TestCleanText -v

# Stop on first failure
pytest tests/ -x

# Show print statements
pytest tests/ -s

# Verbose + coverage + stop on fail
pytest tests/ -v --cov -x --tb=short
```

---

**Status:** ✅ Framework complete | Ready for Pha 4 (CI/CD)

**Next:** GitHub Actions workflow in Pha 4 (2 days)
