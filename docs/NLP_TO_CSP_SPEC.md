# Spec: Giao diện NLP to CSP (Contract)

Tài liệu này định nghĩa cấu trúc JSON chuẩn (payload) mà module NLP sẽ xuất ra để module CSP (Constraint Satisfaction Problem) tiêu thụ. Mọi thay đổi trong schema này cần được thống nhất giữa hai team.

## Cấu trúc tổng quan

Payload là một file/object JSON bao gồm các thành phần:
- `user`: Thông tin cá nhân của người dùng (metadata).
- `goal`: Mục đích chính của request (vd: gợi ý thực đơn, tra cứu dinh dưỡng).
- `constraints`: Các ràng buộc bắt buộc (hard constraints) cần thỏa mãn.
- `variables`: Không gian biến, chứa các lựa chọn ứng viên (candidates).
- `objectives`: Các mục tiêu tối ưu (soft constraints / objective functions).
- `meta`: Metadata về query (source, debug info).

## Định dạng JSON chi tiết

### 1. `user` (Object | Optional)
Luôn chứa các thông tin cá nhân đã được extract ra dưới dạng chuẩn mực. 
Các trường có thể không xuất hiện nếu user không đề cập.

```json
"user": {
  "weight_kg": 70.0,
  "height_cm": 175.0,
  "daily_calorie_target": 1800
}
```

### 2. `goal` (Object | Bắt buộc)
Xác định luồng logic thuật toán CSP cần chạy.

```json
"goal": {
  "type": "recommend_meal" 
}
```
Các `type` hợp lệ: `recommend_meal`, `ask_nutrition`, `update_profile`, `unknown`.

### 3. `constraints` (Object | Bắt buộc)
Các ràng buộc cứng mà CSP phải tuân thủ để lọc kết quả.

```json
"constraints": {
  "exclude": ["hải sản", "tôm"], 
  "dietary_restrictions": ["vegetarian"],
  "budget_vnd_max": 200000,
  "replacement_target": "cơm trắng"
}
```
- `exclude` (List[str]): Các món ăn, dị ứng bắt buộc loại bỏ.
- `dietary_restrictions` (List[str]): Chế độ ăn đặc biệt.
- `budget_vnd_max` (Int): Tổng kinh phí (VND). Không có phần thập phân.
- `replacement_target` (String): Món ăn cần tìm món thay thế.

### 4. `variables` (Object | Bắt buộc)
Cung cấp tập ứng viên được lấy ra từ dữ liệu của người dùng.

```json
"variables": {
  "candidates": [
    {"id": "Gạo tẻ giã", "name": "cơm trắng", "cost_vnd_100g": 1800},
    {"id": "Thịt lợn nạc vai", "name": "thịt lợn", "cost_vnd_100g": 15000}
  ]
}
```
- NLP sẽ gán trực tiếp giá tiền trung bình (dựa trên bảng heuristic từ `price_defaults.json` đã được seeded bằng LLM) vào `cost_vnd_100g`.
- CSP sẽ map các Id này vào DB để lấy thông số (Vector dinh dưỡng).
- Nếu NLP chưa map được (id = `null`), CSP có thể xử lý fallback qua Tên (`name`).

### 5. `objectives` (Object | Bắt buộc)
Mục tiêu giải thuật CSP cần tối ưu chiều nào.

```json
"objectives": {
  "maximize": ["protein_g"],
  "minimize": ["cost_vnd", "fat_g"]
}
```
- Sử dụng chính xác field name của DB như `protein_g`, `fat_g`, `energy_kcal`.

### 6. `meta` (Object | Bắt buộc)
Dùng cho debug hoặc routing.

```json
"meta": {
  "query_keyword": "thay thế",
  "source": "cache",
  "cached_from": "gemini"
}
```

## Ví dụ Payload Mẫu NLP → CSP

**User Query**: *"Tôi muốn thay cơm trắng bằng gì để tăng protein và chất xơ"*
```json
{
  "user": {},
  "goal": {
    "type": "ask_nutrition"
  },
  "constraints": {
    "exclude": [],
    "dietary_restrictions": [],
    "replacement_target": "cơm trắng"
  },
  "variables": {
    "candidates": [
      {
        "id": "Gạo tẻ giã",
        "name": "cơm trắng",
        "cost_vnd_100g": 1800
      }
    ]
  },
  "objectives": {
    "maximize": [
      "protein_g"
    ],
    "minimize": []
  },
  "meta": {
    "query_keyword": "thay thế",
    "source": "gemini",
    "cached_from": null
  }
}
```