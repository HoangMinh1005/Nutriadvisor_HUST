# NutriAdvisor Project Structure

Tài liệu này tóm tắt cấu trúc hiện tại của dự án NutriAdvisor và mục đích chính của từng thư mục.

## Tree Diagram

```text
NutriAdvisor_HUST/
├── backend/                 # FastAPI backend, services, và các module ML
│   ├── app/                 # API routes và service layer
│   └── ml/                  # ML ecosystem: feature store, clustering, ...
├── data/                    # Dữ liệu nguồn, SQL, ETL scripts, cache ML
│   ├── raw/                 # CSV/manifest dữ liệu thô
│   ├── sql/                 # Schema, seed data, query hỗ trợ
│   ├── scripts/             # Loader, migration, merge, crawl scripts
│   └── ml/                  # Feature cache và model cache
├── docs/                    # Tài liệu kiến trúc, kế hoạch, testing, onboarding
├── tests/                   # Unit và integration tests
├── .github/                 # GitHub Actions workflows cho CI/CD
├── api/                     # Tài liệu/API notes cho phần backend
├── csp/                     # Tài liệu/logic liên quan đến CSP meal planning
├── logic/                   # Tài liệu logic nghiệp vụ hoặc các ghi chú cũ
├── ml/                      # README/tài liệu ML cấp cao
├── docker-compose.yml       # Khởi động Postgres, pgAdmin, backend
├── pytest.ini               # Cấu hình pytest
├── requirements-test.txt    # Dependency cho test và quality checks
└── DATABASE_RESET_GUIDE.md  # Hướng dẫn reset database khi cần
```

## Mục Đích Chính Của Các Folder

### `backend/`
Chứa toàn bộ mã nguồn backend. Đây là nơi FastAPI chạy, xử lý API search, tích hợp cơ sở dữ liệu, và triển khai các module ML như Feature Store, K-Means, NLP, KNN, CSP, Regression.

### `data/`
Chứa dữ liệu và pipeline dữ liệu. Thư mục này bao gồm dữ liệu thô, schema SQL, script ETL/load dữ liệu, và cache phục vụ ML.

### `tests/`
Chứa bộ kiểm thử của dự án. Có unit tests, integration tests, và fixture dùng chung để xác minh dữ liệu, backend và ML modules.

### `docs/`
Chứa tài liệu kỹ thuật và tài liệu triển khai. Đây là nơi lưu kiến trúc ML, kế hoạch triển khai, hướng dẫn testing và onboarding.

### `.github/`
Chứa cấu hình CI/CD, đặc biệt là GitHub Actions để chạy lint, unit tests, integration tests, smoke tests và coverage.

### `api/`
Chứa các ghi chú hoặc tài liệu liên quan đến API. Nếu cần tách tài liệu giao tiếp API ra khỏi code backend thì thư mục này hỗ trợ mục đó.

### `csp/`
Chứa tài liệu hoặc logic liên quan đến Constraint Satisfaction Problem, phục vụ module meal planning.

### `logic/`
Chứa tài liệu logic nghiệp vụ, ghi chú thiết kế, hoặc phần nội dung cũ dùng để tham khảo.

### `ml/`
Chứa tài liệu ML cấp cao hoặc README mô tả kiến trúc ML tổng quát.

## Ghi Chú Nhanh

- `backend/ml/feature_store/`: tạo và cache vector dinh dưỡng 14D từ database.
- `backend/ml/clustering/`: K-Means user segmentation đã hoàn thành.
- `data/ml/features/`: cache feature snapshot đã tạo.
- `data/ml/clustering/`: cache model K-Means và scaler.
- `tests/unit/test_*`: kiểm thử logic từng module.
- `tests/integration/test_*`: kiểm thử tích hợp với database và API.

## Trạng Thái Hiện Tại

- Pha 1-4: hoàn thành.
- Feature Store: hoàn thành.
- K-Means User Segmentation: hoàn thành.
- Các module tiếp theo của Pha 5: NLP Engine, KNN Recommender, CSP Meal Planning, Linear Regression.

