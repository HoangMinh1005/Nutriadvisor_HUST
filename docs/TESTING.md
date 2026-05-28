Mục đích
- Hướng dẫn kiểm thử dữ liệu và xác thực pipeline ETL/migrations/loader/search cho dự án NutriAdvisor.

Môi trường cần chuẩn bị
- Python 3.10+ trong virtualenv .venv (kích hoạt trước khi chạy script).
- Docker + Docker Compose: dịch vụ Postgres chạy (container mapped host:5433 để tránh xung đột).
- Biến môi trường: DATABASE_URL (ví dụ: postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor).

Kiểm tra nhanh trước khi load
- Kiểm tra file CSV đầu vào: số cột, tên cột khớp schema 14 nutrients.
- So sánh row counts với manifest: nếu final_nutrients_structured.csv có N hàng thì loader nên nạp N (trừ duplicates xử lý).
- Tính checksum (sha256) của CSV và lưu vào manifest để so sánh.

Validation scripts & checks (gợi ý)
- scripts/validate_csv.py (pandas):
  - Kiểm tra kiểu cột, các giá trị thiếu, range hợp lý (calories >=0, protein/fat/carbs >=0), unit consistency.
  - Tìm duplicates theo canonical_key hoặc canonical_name_en.
- SQL quick-checks (psql / psycopg):
  - SELECT count(*) FROM foods;
  - SELECT count(*) FROM food_aliases;
  - SELECT count(*) FROM food_nutrients;
  - Kiểm tra orphan rows: SELECT f.food_id FROM foods f LEFT JOIN food_nutrients n ON f.food_id=n.food_id WHERE n.food_id IS NULL;

Loader & migration tests
- Migrations (kịch bản):
  - Dry-run: python data/scripts/run_migrations.py --dry-run --database-url "$env:DATABASE_URL"
  - Baseline (khi DB đã init bằng entrypoint): python data/scripts/run_migrations.py --baseline --database-url "$env:DATABASE_URL"
- Loader: chạy với --version-tag và kiểm tra output thống kê.
  - PowerShell example:

  $env:DATABASE_URL = "postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"
  .venv\Scripts\python.exe data/scripts/load_structured_to_db.py --version-tag v1.1.0

Search API integration tests
- Khởi chạy backend: docker compose up -d --build ai-backend hoặc chạy uvicorn backend.app.main:app --reload trong venv.
- Test endpoints:
  - Exact match: /foods/search?q=beef%20noodle%20soup
  - Vietnamese alias: /foods/search?q=thit+bo
  - Typo/fuzzy: /foods/search?q=thitb0  (xem tier đổi từ exact→fuzzy).
- Xác nhận response: tier, items[] có food_id, canonical_key, calories, protein, alias_texts, match_score.

Automated tests (gợi ý)
- Tạo tests/ với pytest:
  - Unit: test helper functions (_clean_text, _to_float).
  - Integration: fixtures để khởi tạo DB test (docker-compose test DB) → chạy migrations → load small sample CSV → gọi API endpoints.
- CI pipeline: bước tối thiểu:
  - Run linter + unit tests
  - Run migrations (dry-run or on ephemeral DB)
  - Run loader against small sample and verify row counts

Debug & Troubleshooting
- Lỗi kết nối DB: kiểm tra port host (Windows thường có Postgres trên 5432) → dùng 5433 container.
- psycopg vs psycopg2: dự án dùng psycopg[binary] cho Python 3.14+.
- Nếu loader chậm: dùng sample nhỏ để dev, cân nhắc bulk path (execute_values) cho production.

Checklist release data
- CSV validated (schema + ranges)
- Manifest/version tag cập nhật
- Migrations đã apply và ghi vào schema_migrations
- Loader chạy thành công với thống kê phù hợp
- `food_source_rows` giữ đủ số dòng gốc, `foods` giữ số dòng canonical sau dedupe
- Backend trả kết quả search mẫu được

Ghi chú ngắn
- Giữ manifest dataset (sha256 + row count + version tag) trong data/ để tái tạo.
- Viết test case mô tả kỳ vọng cho mỗi bug fix liên quan dữ liệu.

Liên hệ
- Nếu cần trợ giúp, ping reviewer chịu phần dữ liệu hoặc tạo issue với "data-validation" tag.
