import urllib.request
import json

def test_chat(message, user_profile=None):
    url = "http://127.0.0.1:8000/api/v1/chat"
    payload = {"message": message}
    if user_profile:
        payload["user_profile"] = user_profile
        
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_body = response.read().decode("utf-8")
            data = json.loads(res_body)
            print(f"\nQuery: '{message}'")
            print("Response Status:", response.status)
            print("Response Data:", json.dumps(data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error for '{message}': {e}")

print("=== Starting Live Chat API Verification ===")
# 1. Out of Scope
test_chat("Thời tiết hôm nay thế nào?")
# 2. Query nutrition
test_chat("Ức gà có bao nhiêu calo?")
# 3. Alternatives
test_chat("Thay thế cơm trắng bằng gì?")
# 4. Suggest meal
test_chat("Gợi ý thực đơn tăng cơ 1800 calo", user_profile={"goal": "gym", "daily_calorie_target": 1800})
