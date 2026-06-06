import sys
sys.path.insert(0, ".")

from csp.scheduler import get_dynamic_tags

rich_mock_foods = [
    {"food_id": 1, "canonical_name_en": "Chicken Breast", "name_vi": "ức gà", "category": "thịt_gia_cầm"},
    {"food_id": 2, "canonical_name_en": "Egg", "name_vi": "trứng", "category": "trứng"},
    {"food_id": 3, "canonical_name_en": "Oats", "name_vi": "yến mạch", "category": "tinh_bột"},
    {"food_id": 4, "canonical_name_en": "White Rice", "name_vi": "cơm trắng", "category": "tinh_bột"},
    {"food_id": 5, "canonical_name_en": "Beef", "name_vi": "thịt bò", "category": "thịt_đỏ"},
    {"food_id": 6, "canonical_name_en": "Salmon", "name_vi": "cá hồi", "category": "cá_hải_sản"},
    {"food_id": 7, "canonical_name_en": "Milk", "name_vi": "sữa tươi", "category": "sữa"},
    {"food_id": 8, "canonical_name_en": "Banana", "name_vi": "chuối", "category": "trái_cây"},
    {"food_id": 9, "canonical_name_en": "Cabbage", "name_vi": "rau cải", "category": "rau_xanh"},
    {"food_id": 10, "canonical_name_en": "Duck", "name_vi": "thịt vịt", "category": "thịt_gia_cầm"},
    {"food_id": 11, "canonical_name_en": "Bread", "name_vi": "bánh mì", "category": "tinh_bột"},
    {"food_id": 12, "canonical_name_en": "Sweet Potato", "name_vi": "khoai lang", "category": "tinh_bột"},
    {"food_id": 13, "canonical_name_en": "Pork", "name_vi": "thịt heo", "category": "thịt_lợn"},
    {"food_id": 14, "canonical_name_en": "Spinach", "name_vi": "rau bó xôi", "category": "rau_xanh"},
    {"food_id": 15, "canonical_name_en": "Broccoli", "name_vi": "súp lơ xanh", "category": "rau_xanh"},
    {"food_id": 16, "canonical_name_en": "Brown Rice", "name_vi": "cơm lứt", "category": "tinh_bột"},
    {"food_id": 17, "canonical_name_en": "Beef Pho", "name_vi": "Phở bò chín bình dân", "category": "món_chính"},
    {"food_id": 18, "canonical_name_en": "Stir-fried Noodles", "name_vi": "Mỳ xào thập cẩm", "category": "món_chính"},
    {"food_id": 19, "canonical_name_en": "Dried Jackfruit", "name_vi": "Mít khô", "category": "đồ_ăn_vặt"},
    {"food_id": 20, "canonical_name_en": "Tuna", "name_vi": "cá ngừ tươi", "category": "cá_hải_sản"},
    {"food_id": 21, "canonical_name_en": "Shrimp", "name_vi": "tôm", "category": "cá_hải_sản"},
    {"food_id": 22, "canonical_name_en": "Morning Glory", "name_vi": "rau muống", "category": "rau_xanh"},
    {"food_id": 23, "canonical_name_en": "Nấm rơm", "name_vi": "nấm rơm", "category": "rau_xanh"},
]

for f in rich_mock_foods:
    tags = get_dynamic_tags(f)
    print(f"ID {f['food_id']} ({f['name_vi']}): {sorted(list(tags))}")
