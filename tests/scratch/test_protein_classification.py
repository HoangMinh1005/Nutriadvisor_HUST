import sys
sys.path.append('.')
from csp.scheduler import is_high_quality_protein, get_food_role

# Test mock food items
foods = [
    {'name_vi': 'trứng', 'canonical_name_en': 'Egg', 'category': 'trứng'},
    {'name_vi': 'ức gà', 'canonical_name_en': 'Chicken Breast', 'category': 'thịt_gia_cầm'},
    {'name_vi': 'thịt vịt', 'canonical_name_en': 'Duck', 'category': 'thịt_gia_cầm'},
    {'name_vi': 'thịt bò', 'canonical_name_en': 'Beef', 'category': 'thịt_đỏ'},
    {'name_vi': 'cá hồi', 'canonical_name_en': 'Salmon', 'category': 'cá_hải_sản'},
    {'name_vi': 'thịt heo', 'canonical_name_en': 'Pork', 'category': 'thịt_lợn'},
    {'name_vi': 'Lòng trắng trứng sấy khô', 'canonical_name_en': 'Egg, dried, white', 'category': 'trứng'},
    {'name_vi': 'tôm', 'canonical_name_en': 'Shrimp', 'category': 'cá_hải_sản'},
]
for f in foods:
    is_p, is_c, is_f = get_food_role(f)
    hq = is_high_quality_protein(f)
    name = f['name_vi']
    print(f"{name:30s}  is_protein={is_p!s:5s}  is_high_quality={hq!s:5s}")
