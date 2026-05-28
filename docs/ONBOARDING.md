Mục tiêu
- Giúp thành viên mới nhanh chóng cài đặt môi trường, chạy migrations, load dữ liệu mẫu và kiểm tra endpoint search.

Tổ chức repository (tóm tắt)
- data/: scripts ETL, SQL migrations, CSV inputs, manifests
  - data/scripts/: run_migrations.py, load_structured_to_db.py, merge_nutrients.py
  - data/sql/: migration files (init)
- backend/: FastAPI app và dịch vụ search
- docker-compose.yml: Postgres, pgadmin, ai-backend

Bước 1 — Thiết lập local
1. Clone repo
2. Tạo virtualenv và cài dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Bước 2 — Khởi động DB và backend
- Khởi động docker dịch vụ:

```powershell
docker compose up -d --build
```

- DB mặc định mapped host:5433. Nếu host có Postgres khác, dùng 5433.

Bước 3 — Run migrations & load sample data
- Dry-run và baseline migrations:

```powershell
$env:DATABASE_URL = "postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"
python data/scripts/run_migrations.py --dry-run --database-url "$env:DATABASE_URL"
python data/scripts/run_migrations.py --baseline --database-url "$env:DATABASE_URL"
```

- Load dữ liệu đã chuẩn hoá:

```powershell
$env:DATABASE_URL = "postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"
.venv\Scripts\python.exe data/scripts/load_structured_to_db.py --version-tag v1.1.0
```

- Nếu muốn dựng lại DB từ trạng thái sạch và đảm bảo `food_id` chạy liên tục từ 1, dùng:

```powershell
$env:DATABASE_URL = "postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"
.venv\Scripts\python.exe data/scripts/load_structured_to_db.py --version-tag v1.1.0 --reset
```

- `--reset` sẽ xóa các bảng dữ liệu liên quan đến food, nạp lại bảng raw `food_source_rows`, rồi mới nạp canonical `foods` và `food_nutrients`.

Bước 4 — Kiểm tra API
- Gọi:
  - http://127.0.0.1:8000/foods/search?q=thit+bo
- Xác nhận nhận được JSON như mô tả trong docs/TESTING.md

Coding & PR checklist
- Viết unit tests cho logic mới liên quan dữ liệu
- Chạy `python -m pytest tests/`
- Thêm entry vào changelog nếu cập nhật schema hoặc seed data

FAQ nhanh
- Lỗi kết nối Postgres: kiểm tra `DATABASE_URL` và port.
- Lỗi package: đảm bảo virtualenv active và pip install thành công.
- Thấy `foods` ít hơn CSV gốc: đó là do dedupe theo `canonical_key`; dữ liệu gốc vẫn được giữ trong `food_source_rows`.

Người hỗ trợ
- Reviewer dữ liệu: @data-lead
- Reviewer backend: @backend-lead

Chào mừng bạn tham gia! Nếu cần, tôi có thể tạo sẵn một branch `ci/tests` với mẫu GitHub Actions để chạy migrations + tests tự động.
