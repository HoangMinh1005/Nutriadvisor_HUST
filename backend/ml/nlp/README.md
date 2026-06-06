# NLP Engine MVP

MVP cho Pha 5 Module 1 của NutriAdvisor.

## Pipeline

- Local: TF-IDF char n-grams + MultinomialNB
- Extraction: regex cho `budget_vnd`, `calories`, `health_goal`, `allergies`, `dietary_restrictions`
- Extraction v2: thêm `query_keyword`, `profile_updates`, `replacement_target`
- Cache: Redis nếu có, fallback in-memory nếu không có Redis; cache key có namespace theo `schema/prompt/model`
- Fallback: Gemini API trả JSON strict
- Confidence threshold mặc định: `0.7` để ưu tiên local nhiều hơn nhưng vẫn giữ độ chính xác

## Env Vars

- `GEMINI_API_KEY`: bắt buộc nếu muốn dùng fallback Gemini
- `GEMINI_MODEL`: mặc định `gemini-2.5-flash`
- `NLP_CACHE_URL`: Redis URL, nếu không có thì dùng cache bộ nhớ
- `NLP_CONFIDENCE_THRESHOLD`: ngưỡng confidence để quyết định fallback, mặc định `0.7`

Nếu chạy qua `docker compose`, backend sẽ dùng Redis service nội bộ (`redis://redis:6379/0`).
Nếu chạy local mà thấy cache báo `memory`, hãy kiểm tra venv đã cài `redis` Python package chưa và đảm bảo Redis đang nghe ở URL trong `NLP_CACHE_URL`.

Lưu ý: các câu có từ khóa như `gym` / `tập gym` được xem là tín hiệu mạnh cho `health_goal=muscle_gain`.
Ngoài ra, các câu có ngữ nghĩa ngân sách/tiết kiệm được gán `query_keyword=budget_conscious`; câu hỏi thay thế món ăn được gán `query_keyword=replacement`.

## Quick Start

```bash
python -m backend.ml.nlp.demo "Tôi muốn thực đơn 100k mỗi ngày để tăng cơ, không có hải sản"
```

## Test nhanh local vs Gemini

Nếu bạn vừa đổi threshold hoặc bổ sung data, hãy xóa cache rồi test lại để tránh kết quả cũ:

```bash
python -c "from backend.ml.nlp.intent_engine import IntentEngine; e = IntentEngine(); e.ensure_ready(); e.cache.clear(); print(e.predict('tôi 70 kg').to_dict())"
```

Nếu chỉ muốn chạy demo và xem `source`/`confidence`:

```bash
python -m backend.ml.nlp.demo "tôi hiện đã giảm còn 70kg hiện tôi muốn giữ nguyên cân nặng và tăng cơ hãy gợi ý thực đơn mới"

python -m backend.ml.nlp.demo "Tôi là nữ sinh năm 1998, cao 165cm, nặng 58kg và muốn ăn 1800 kcal mỗi ngày"

python -m backend.ml.nlp.demo "Tôi muốn thay cơm trắng bằng gì để tăng protein và chất xơ"
```
