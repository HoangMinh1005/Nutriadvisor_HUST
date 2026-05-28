# Database Reset & Management Guide

## Overview
Khi chạy `docker-compose up`, PostgreSQL sẽ tự động thực thi các file SQL trong thư mục `./data/sql/` theo thứ tự:
1. `001_schema.sql` - Tạo các bảng chính
2. `002_seed_categories.sql` - Seed dữ liệu category

Backend sẽ tự động kiểm tra database readiness khi khởi động (qua `check_db.py`).

---

## 1. Khởi động lần đầu (Fresh Start)
```bash
# Điều hướng đến thư mục dự án
cd d:\Minh\NutriAdvisor_HUST

# Build & start services
docker compose up -d --build
```

**Kiểm tra trạng thái:**
```bash
docker compose ps
docker compose logs ai-backend
```

Nếu thấy output từ `check_db.py` trong logs với `✅ ALL CHECKS PASSED`, database đã sẵn sàng.

---

## 2. Reset Database (Xóa toàn bộ dữ liệu cũ)

### Cách 1: Xóa volume & khởi động lại (Khuyến nghị)
```bash
# Dừng services
docker compose down

# Xóa volume data (CẨN THẬN - tất cả dữ liệu sẽ mất)
docker volume rm nutriadvisor_hust_postgres_data

# Khởi động lại - SQL scripts sẽ chạy từ đầu
docker compose up -d --build
```

### Cách 2: Xóa database hiện tại mà không xóa volume
```bash
# Vào PostgreSQL container
docker compose exec postgres psql -U nutri_user -d nutri_advisor

# Trong psql shell, chạy:
DROP TABLE IF EXISTS meal_plans CASCADE;
DROP TABLE IF EXISTS food_tag_mapping CASCADE;
DROP TABLE IF EXISTS food_tags CASCADE;
DROP TABLE IF EXISTS user_profiles CASCADE;
DROP TABLE IF EXISTS foods CASCADE;
DROP TABLE IF EXISTS categories CASCADE;

# Thoát psql
\q
```

Sau đó chạy lại SQL scripts manually:
```bash
# 001_schema.sql
docker compose exec -T postgres psql -U nutri_user -d nutri_advisor < data/sql/001_schema.sql

# 002_seed_categories.sql
docker compose exec -T postgres psql -U nutri_user -d nutri_advisor < data/sql/002_seed_categories.sql
```

---

## 3. Chạy SQL Scripts Manually (Nếu cần update)

Nếu bạn chỉnh sửa nội dung file SQL và muốn chạy lại:

```bash
# Chạy từng file theo thứ tự
docker compose exec -T postgres psql -U nutri_user -d nutri_advisor < data/sql/001_schema.sql
docker compose exec -T postgres psql -U nutri_user -d nutri_advisor < data/sql/002_seed_categories.sql
```

**Lưu ý:** Nếu table đã tồn tại, `CREATE TABLE IF NOT EXISTS` sẽ skip nó. Dùng **Cách 1 (reset volume)** nếu muốn clean slate.

---

## 4. Kiểm tra Database từ pgAdmin

- Truy cập: http://localhost:5050
- Đăng nhập: `admin@nutriadvisor.com` / `change_me_pgadmin`
- Thêm server: 
  - Hostname: `postgres` (hoặc `nutri-postgres`)
  - Port: `5432`
  - Username: `nutri_user`
  - Password: `change_me_securely` (từ `.env`)
- Xem các bảng trong `Databases > nutri_advisor > Schemas > public > Tables`

---

## 5. Kiểm tra Database từ CLI

```bash
# Vào PostgreSQL container
docker compose exec postgres psql -U nutri_user -d nutri_advisor

# Danh sách bảng
\dt

# Xem cấu trúc bảng
\d foods
\d categories

# Đếm record trong bảng
SELECT COUNT(*) FROM categories;
SELECT COUNT(*) FROM foods;

# Thoát
\q
```

---

## 6. Debug Backend Database Check

Nếu backend log cho thấy database check fail:

```bash
# Xem log chi tiết
docker compose logs ai-backend -f

# Hoặc chạy check manually
docker compose exec ai-backend python -m app.check_db
```

---

## Troubleshooting

### pgAdmin restart loop
- **Vấn đề:** Email format không hợp lệ
- **Fix:** Kiểm tra `PGADMIN_DEFAULT_EMAIL` trong `.env` phải là email hợp lệ (e.g., `admin@nutriadvisor.com`)

### Backend can't connect to database
- **Vấn đề:** DATABASE_URL không đúng hoặc PostgreSQL chưa ready
- **Fix:** 
  - Kiểm tra `docker compose logs postgres`
  - Đợi healthcheck pass (status: `healthy`)
  - Kiểm tra environment variables trong backend service

### SQL files not executing on first start
- **Vấn đề:** Volume mount có vấn đề
- **Fix:** 
  - Xóa volume: `docker volume rm nutriadvisor_hust_postgres_data`
  - Kiểm tra path trong `docker-compose.yml`: `./data/sql:/docker-entrypoint-initdb.d`
  - Khởi động lại: `docker compose up -d --build`

---

## Cấu trúc các file SQL

```
data/sql/
├── 001_schema.sql              # CREATE TABLE statements
├── 002_seed_categories.sql     # INSERT default categories
└── knn_feature_queries.sql     # Sample queries for ML
```

**PostgreSQL sẽ chạy các file `.sql` trong alphabetical order từ `/docker-entrypoint-initdb.d/`**

---

## Reset Everything (Full Clean)

Nếu muốn xóa tất cả container, images, volumes:

```bash
# Dừng services
docker compose down

# Xóa volume
docker volume rm nutriadvisor_hust_postgres_data nutriadvisor_hust_pgadmin_data

# Xóa image (optional)
docker rmi nutriadvisor_hust-ai-backend dpage/pgadmin4 postgres:13

# Khởi động clean
docker compose up -d --build
```

---

**Lưu ý:** Luôn backup dữ liệu quan trọng trước khi reset volumes!
