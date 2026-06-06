# Roadmap: Chuyển từ NLP sang CSP (Constraint Satisfaction Problem)

Tài liệu này mô tả trạng thái hiện tại của module NLP và các bước cần thực hiện để chuyển sang phát triển thuật toán CSP, kèm thứ tự ưu tiên, ước lượng thời gian, và các kiểm tra cần có.

## 1. Tóm tắt trạng thái hiện tại
- Pipeline hybrid: TF‑IDF + MultinomialNB (local) với fallback Gemini (LLM).
- Entity extraction phong phú: `profile_updates`, `food_items`, `nutrients`, `replacement_target`, `budget_vnd`, `allergies`, `dietary_restrictions`, `query_keyword`.
- Cache: `IntentCache` hỗ trợ Redis (về namespace = `SCHEMA_VERSION:PROMPT_VERSION:MODEL`), fallback in‑memory, negative cache cho 429, singleflight lock.
- Đã bổ sung: `IntentEngine.to_csp_payload()` helper, `NLPResult.cached_from`, và `requirements-dev.txt` nhẹ.
- Unit tests: test suite cho NLP đã chạy thành công (19 tests).

## 2. Mục tiêu khi chuyển sang CSP
- NLP phải xuất payload chuẩn, có thể tiêu thụ trực tiếp bởi CSP solver.
- CSP cần các input có thể map tới DB (food_item_id), các trường dinh dưỡng chuẩn (ví dụ `protein_g`, `energy_kcal`), số nguyên cho budget và đơn vị chuẩn cho lượng (gram).
- Tích hợp phải có kiểm thử tự động (unit + smoke) để phát hiện mismatch sớm.

## 3. Giao diện (contract) NLP → CSP (bắt buộc)
Ví dụ payload tối thiểu mà `to_csp_payload()` phải tạo:

```json
{
  "user": {"weight_kg": 70, "height_cm": 175, "daily_calorie_target": 1800},
  "goal": {"type": "recommend_meal"},
  "constraints": {
    "exclude": ["hải sản"],
    "dietary_restrictions": ["vegetarian"],
    "budget_vnd_max": 100000,
    "replacement_target": "cơm trắng"
  },
  "variables": {"candidates": ["ức gà","trứng","yến mạch"]},
  "objectives": {"maximize": ["protein_g"], "minimize": ["cost_vnd"]},
  "meta": {"query_keyword": "thay thế", "source": "cache", "cached_from": "gemini"}
}
```

Yêu cầu contract:
- `variables.candidates` nên chứa `food_item_id` nếu có DB; nếu chưa, chứa canonical name.
- `objectives` dùng tên nutrient chuẩn khớp schema DB.
- `constraints` có `exclude`, `budget_vnd_max`, `replacement_target` (tùy case).

## 4. Danh sách việc BẮT BUỘC trước khi chuyển sang CSP (ưu tiên cao)
1. Finalize contract NLP→CSP và document (file): `docs/NLP_TO_CSP_SPEC.md`.
   - Hành động: kiểm tra `to_csp_payload()` hiện tại, hoàn thiện spec và ví dụ. 1–2 giờ.
2. Food-item → canonical ID mapping
   - Hành động: xây helper mapping (file CSV/JSON mapping tên → `food_item_id`), thêm fuzzy matching fallback. 4–8 giờ.
   - Kiểm tra: unit tests map chính xác cho các tên phổ biến.
3. Chuẩn hoá nutrient field names
   - Hành động: xác nhận `NUTRIENT_FIELD_ALIASES` khớp DB; thêm test coverage. 1–2 giờ.
4. Budget & quantity normalization
   - Hành động: đảm bảo `budget_vnd` là integer VND, lượng (serving) chuẩn g. 0.5–1 giờ.
5. Mở rộng unit tests cho `to_csp_payload()`
   - Hành động: thêm cases (replacement, recommend, ask_nutrition, budget-only). 1–2 giờ.
6. Cache provenance & namespace verification
   - Hành động: đảm bảo cached payload có `source: "cache"` và `cached_from` (đã implement); thêm smoke test kiểm tra `IntentCache.mode`. 0.5–1 giờ.

## 5. Kiểm tra tích hợp sớm (smoke tests)
- Tạo stub CSP checker (script nhỏ) nhận payload và xác nhận: fields tồn tại, `variables.candidates` không rỗng, nutrient names hợp lệ, budget là số.
- Viết CI job để chạy smoke test sau step unit tests. Ước lượng 1–2 giờ.

## 6. Dev experience & môi trường
- Đã thêm `backend/requirements-dev.txt` để dev NLP/CSP không phải cài pandas native builds.
- Document cách chạy local (venv) hoặc chạy qua Docker (khi cần full deps). Thêm hướng dẫn chạy Redis local hoặc dùng Docker Compose. 0.5–1 giờ.

## 7. Monitoring & safety (khuyến nghị trước deploy)
- Triển khai metrics cơ bản: `intent_cache_hits`, `intent_cache_misses`, `gemini_requests_total`, `gemini_429_total`, `gemini_latency`.
- Giúp theo dõi tỷ lệ cache, số lần fallback LLM, và tắc nghẽn khi tích hợp CSP. 2–4 giờ.

## 8. Bảo mật & test data
- Không commit `GEMINI_API_KEY`; hướng dẫn dùng env hoặc secret manager.
- Cho CSP dev dùng mock LLM responses (đã có trong tests bằng hàm giả). 0.5–1 giờ.

## 9. Deterministic schema versioning & migration plan
- Ghi rõ `SCHEMA_VERSION`/`PROMPT_VERSION` và cách đổi khi thay schema (tạo namespace cache mới, migrate nếu cần). 0.5–1 giờ.

## 10. Checklist triển khai (trước khi CSP team bắt viết thuật toán)
- [ ] `docs/NLP_TO_CSP_SPEC.md` hoàn chỉnh và được review.
- [ ] Mapping file `data/food_mapping.json` và helper implemented + tests.
- [ ] `to_csp_payload()` cover các trường hợp quan trọng và tests pass.
- [ ] Smoke test chạy: NLP → stub CSP checker.
- [ ] Dev instructions updated (README) + `requirements-dev.txt` có sẵn.
- [ ] Cache provenance và namespace/versioning kiểm tra xong.

## 11. Lộ trình khuyến nghị (thực thi)
1. Finalize spec + small doc (1–2h).
2. Implement food mapping & fuzzy match (4–8h).
3. Normalize nutrients & budget (1–2h).
4. Expand tests + smoke checker (1–2h).
5. Optional: instrument metrics (2–4h).

Tổng ước lượng (để có trạng thái sẵn sàng cho CSP): ~8–16 giờ làm việc (tuỳ chi tiết mapping và data quality).

## 12. Các lệnh kiểm thử nhanh
- Chạy unit tests NLP:

```bash
d:/Minh/NutriAdvisor_HUST/.venv/Scripts/python.exe -m pytest tests/unit/test_nlp_engine.py -q
```

- In payload demo:

```bash
d:/Minh/NutriAdvisor_HUST/.venv/Scripts/python.exe -c "from backend.ml.nlp.intent_engine import IntentEngine; import json; e=IntentEngine(); e.ensure_ready(); r=e.predict('Tôi muốn thay cơm trắng bằng gì để tăng protein và chất xơ'); print(json.dumps(e.to_csp_payload(r), ensure_ascii=False, indent=2))"
```

## 13. Next steps đề xuất ngay
1. Mình sẽ tạo `docs/NLP_TO_CSP_SPEC.md` chi tiết và một stub `data/food_mapping.sample.json` nếu bạn đồng ý. (Tự động thực hiện nếu bạn gõ `OK`.)

---
Tài liệu này nhằm giúp chuyển giao clean data từ NLP sang CSP nhanh nhất với ít rủi ro. Nếu bạn đồng ý, mình sẽ tiến hành tạo spec chi tiết và file mapping mẫu ngay.
