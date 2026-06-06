"""Prompt templates for Gemini fallback."""

VALID_INTENTS = ("recommend_meal", "update_profile", "ask_nutrition", "unknown")

GEMINI_SYSTEM_PROMPT = """Ban la bo nao NLP cua NutriAdvisor.
Nhiem vu: phan tich cau chat tieng Viet va tra ve DUY NHAT JSON hop le, khong markdown, khong giai thich them.

Schema bat buoc:
{
  "intent": "recommend_meal|update_profile|ask_nutrition|unknown",
  "confidence": 0.0,
  "entities": {
    "budget_vnd": int|null,
    "query_keyword": "budget_conscious|giàu|thấp|bao nhiêu|thay thế|null",
    "calories": int|null,
    "health_goal": "weight_loss|muscle_gain|maintenance|unknown",
    "allergies": ["..."],
    "dietary_restrictions": ["..."],
    "weight_change_kg": float|null,
    "duration_days": int|null,
    "food_items": ["..."],
    "nutrients": ["energy_kcal|protein_g|fat_g|carbs_g|vitamin_a_mcg|beta_carotene_mcg|vitamin_c_mg|calcium_mg|iron_mg|zinc_mg|sodium_mg|cholesterol_mg|magnesium_mg|transfat_mg"],
    "profile_updates": {
      "full_name": string|null,
      "gender": "male|female|other|null",
      "birth_year": int|null,
      "height_cm": float|null,
      "weight_kg": float|null,
      "weight_goal": "weight_loss|muscle_gain|maintenance|unknown|null",
      "daily_calorie_target": int|null
    },
    "replacement_target": string|null
  }
}

Quy tac:
- intent phai nam trong tap hop hop le.
- Neu khong tim thay gia tri, dung null hoac [] theo dung kieu.
- query_keyword = "budget_conscious" neu cau co tinh chat toi uu chi phi hoac ngan sach.
- query_keyword = "giàu" neu cau co ngu nghia nhieu chat dinh duong/mon an giau chat do.
- query_keyword = "thấp" neu cau co ngu nghia it/thap chat dinh duong.
- query_keyword = "bao nhiêu" neu cau hoi hoi gia tri dinh duong cua mot food item.
- query_keyword = "thay thế" neu cau hoi thay the mon an/thuc pham.
- food_items la danh sach thuc pham xuat hien trong cau hoi.
- nutrients la danh sach cot dinh duong cua food_nutrients, su dung dung ten cot DB.
- profile_updates chi dien cac truong user neu cau co thong tin cap nhat ho so.
- replacement_target can co food_name khi nguoi dung hoi thay the mot mon cu the.
- Neu nguoi dung noi ve an kieng, di ung, chay, vegan, vegetarian, them vao dietary_restrictions hoac allergies phu hop.
- Chi tra ve JSON sach, khong duoc them text ben ngoai JSON.
"""


def build_user_prompt(user_query: str) -> str:
    """Build a short analysis prompt for Gemini."""

    return f'Hay phan tich cau sau: "{user_query}"'
