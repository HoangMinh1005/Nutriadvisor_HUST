"""Shared food classification and tagging rules - Upgraded to prevent conflicts."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Set


def _normalize_for_matching(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize('NFKC', text).lower()
    for char in ".,()[]{}/\\-_+*?!:;\"'":
        text = text.replace(char, " ")
    return re.sub(r'\s+', ' ', text).strip()


def get_dynamic_tags(food: Dict[str, Any]) -> Set[str]:
    """Dynamically generate tags for a food item using rules."""
    name_vi = food.get("name_vi") or ""
    name_en = food.get("canonical_name_en") or food.get("name_en") or ""
    cat = food.get("category") or ""
    
    n_vi = _normalize_for_matching(name_vi)
    n_en = _normalize_for_matching(name_en)
    n_cat = _normalize_for_matching(cat)

    def has_any(keywords: list[str]) -> bool:
        for kw in keywords:
            kw_norm = _normalize_for_matching(kw)
            for t in (n_vi, n_en, n_cat):
                if f" {kw_norm} " in f" {t} ":
                    return True
        return False

    def has_any_name(keywords: list[str]) -> bool:
        for kw in keywords:
            kw_norm = _normalize_for_matching(kw)
            for t in (n_vi, n_en):
                if f" {kw_norm} " in f" {t} ":
                    return True
        return False

    tags = set()

    # 1. Allergens
    seafood_kws = ["cá", "tôm", "cua", "hải sản", "seafood", "fish", "shrimp", "crab", "salmon", "tuna", "herring", "mackerel", "mực", "bạch tuộc", "sò", "hàu", "nghêu", "ốc", "hến", "sứa", "chả cá"]
    if has_any(seafood_kws):
        tags.add("allergen_seafood")

    egg_kws = ["trứng", "egg", "eggs", "yolk", "egg white", "egg whites", "egg yolk", "lòng đỏ", "lòng trắng"]
    if has_any(egg_kws):
        tags.add("allergen_egg")

    peanut_kws = ["lạc", "đậu phộng", "peanut", "peanuts"]
    if has_any(peanut_kws):
        tags.add("allergen_peanut")

    milk_kws = ["sữa", "milk", "butter", "cheese", "phô mai", "pho mai", "yogurt", "sữa chua", "whey", "lactose", "váng sữa", "sữa đặc"]
    is_milk = has_any(milk_kws)
    if not is_milk:
        if "bơ" in name_vi.lower().split() or "butter" in n_en:
            if not any(k in n_vi for k in ["quả bơ", "bơ sáp", "bơ quả", "bơ tươi"]):
                is_milk = True
    if is_milk:
        tags.add("allergen_milk")

    soy_kws = ["đậu nành", "đậu phụ", "tofu", "soy", "soya", "tào phớ"]
    if has_any(soy_kws):
        tags.add("allergen_soy")

    wheat_kws = ["lúa mì", "bột mì", "wheat", "gluten", "bánh mì", "bread"]
    if has_any(wheat_kws):
        tags.add("allergen_wheat")

    beef_kws = ["bò", "beef", "veal"]
    if has_any(beef_kws):
        tags.add("allergen_beef")

    pork_kws = ["heo", "lợn", "pork", "bacon", "lạp xưởng", "xúc xích"]
    if has_any(pork_kws):
        tags.add("allergen_pork")

    chicken_kws = ["gà", "chicken"]
    if has_any(chicken_kws):
        tags.add("allergen_chicken")

    duck_kws = ["vịt", "duck"]
    if has_any(duck_kws):
        tags.add("allergen_duck")

    # 2. Roles
    protein_cats = ["gia_cam", "thit_do", "hai_san", "trung", "sua_che_pham", "thịt gia cầm", "gia cầm", "thịt đỏ", "hải sản", "trứng", "sữa và chế phẩm", "sữa"]
    protein_kws = ["chicken", "gà", "beef", "bò", "pork", "heo", "fish", "cá", "salmon", "hồi", "duck", "vịt", "egg", "trứng", "yolk", "lòng đỏ", "egg white", "egg whites", "lòng trắng", "salami", "bacon", "turkey", "shrimp", "tôm", "crab", "cua", "cheese", "phô mai", "yogurt", "sữa chua"]
    if any(n_cat == _normalize_for_matching(c) for c in protein_cats) or has_any(protein_kws):
        tags.add("role_protein")

    carb_cats = ["tinh_bot", "tinh bột"]
    carb_kws = ["rice", "cơm", "oat", "yến mạch", "bread", "bánh mì", "potato", "khoai tây", "cornstarch", "tinh bột", "popcorn", "cakes", "pudding", "ngũ cốc"]
    if any(n_cat == _normalize_for_matching(c) for c in carb_cats) or has_any(carb_kws):
        if not has_any_name(["chè", "che "]):
            tags.add("role_carb")

    fiber_cats = ["rau_cu", "trai_cay", "rau củ", "trái cây", "rau", "rau_xanh"]
    fiber_kws = ["cabbage", "cải", "vegetable", "rau", "salad", "xà lách", "onion", "hành", "fruit", "trái cây", "banana", "chuối", "muống", "bó xôi", "súp lơ", "nấm", "quả", "táo", "cam", "nho", "xoài"]
    if any(n_cat == _normalize_for_matching(c) for c in fiber_cats) or has_any(fiber_kws):
        tags.add("role_fiber")

    # 3. Clean protein
    exclude_clean_kws = [
        "vặt", "tráng miệng", "bánh", "kẹo", "chè", "kem",
        "hộp", "canned", "pate", "lạp xưởng", "xúc xích", "đường"
    ]
    clean_protein_kws = [
        "ức gà", "uc ga", "chicken breast", "thịt bò", "thit bo", "beef", "bắp bò",
        "trứng", "egg", "cá hồi", "salmon", "cá ngừ", "tuna", "thịt lợn", "thịt heo", "pork",
        "vịt", "duck", "tôm", "shrimp", "cua", "crab", "thịt nạc", "thịt gia cầm"
    ]
    if "role_protein" in tags:
        if not has_any(exclude_clean_kws):
            if_clean = has_any(clean_protein_kws) and not has_any_name(["sống", "raw"])
            if if_clean:
                tags.add("clean_protein")

    # 4. Portion limits
    if has_any_name(["khô", "sấy", "dried"]):
        tags.add("is_dried")
    if has_any_name(["bột", "powder", "whey"]):
        tags.add("is_powder")
    if has_any_name(["hộp", "canned", "sốt cà chua", "pate", "lạp xưởng", "xúc xích"]):
        tags.add("is_processed")
    if has_any_name(["phô mai", "pho mai", "cheese", "bơ", "butter"]) and not any(k in n_vi for k in ["quả bơ", "bơ sáp"]):
        tags.add("is_cheese_butter")
    if has_any_name(["sữa đặc", "condensed"]):
        tags.add("is_condensed_milk")
    if has_any_name(["tiết", "blood"]):
        tags.add("is_blood")

    dessert_cats = ["đồ_ăn_vặt", "đồ ăn vặt", "bánh_kẹo", "bánh kẹo", "tráng_miệng", "tráng miệng"]
    dessert_kws = ["bánh ngọt", "bánh kẹo", "chè", "dessert", "kẹo", "bim bim", "snack", "vặt", "tráng miệng"]
    if any(n_cat == _normalize_for_matching(c) for c in dessert_cats) or has_any(dessert_kws):
        tags.add("is_dessert_snack")

    main_dish_cats = ["mon_chinh", "chao", "xoi", "banh_bao", "mon_nuoc", "banh_cuon", "banh_chung_banh_tet", "mon_an_che_bien", "mon_an_che_bien_san", "món chính", "cháo", "xôi", "bánh bao", "món nước", "bánh cuốn", "bánh chưng bánh tét", "món ăn chế biến", "món ăn chế biến sẵn"]
    if any(n_cat == _normalize_for_matching(c) for c in main_dish_cats):
        tags.add("is_main_dish")

    return tags


def check_category(cat: str, target: str) -> bool:
    cat = cat.lower().strip()
    target = target.lower().strip()
    if target == "gia vị, nước chấm":
        return cat == "gia vị, nước chấm" or "gia_vi" in cat
    if target == "nước giải khát":
        return cat == "nước giải khát" or "nuoc_giai_khat" in cat
    if target == "đồ hộp":
        return cat == "đồ hộp" or "do_hop" in cat
    if target == "rau, quả, củ dùng làm rau":
        return cat in ["rau, quả, củ dùng làm rau", "rau, quả và sản phẩm chế biến", "rau_cu", "rau_xanh"]
    if target == "thịt và sản phẩm chế biến":
        return cat in ["thịt và sản phẩm chế biến", "thịt, thủy sản và sản phẩm chế biến", "thit_do", "gia_cam", "thịt_gia_cầm", "thịt_đỏ", "thịt_lợn"]
    if target == "thủy sản và sản phẩm chế biến":
        return cat in ["thủy sản và sản phẩm chế biến", "thịt, thủy sản và sản phẩm chế biến", "hai_san", "cá_hải_sản"]
    if target == "trứng và sản phẩm chế biến":
        return cat in ["trứng và sản phẩm chế biến", "trung"]
    return target in cat


def classify_food(f: Dict[str, Any]) -> str:
    """Classify food into one of the 4 CSP meal roles with advanced filtering against sweet pastries."""
    if "meal_role" in f and f["meal_role"] is not None:
        name_check = str(f.get("name_vi") or "").lower()
        if any(k in name_check for k in ['bánh dẻo', 'bánh nướng', 'nước ướp', 'nước sốt', 'sốt', 'mẻ', 'giấm', 'tương ngô', 'tương nếp']):
            return "ACCESSORY_CONDIMENT"
        return f["meal_role"]
        
    name_vi = str(f.get("name_vi") or "").lower()
    category = str(f.get("category") or "")
    tags = f.get("tags") or set()
    if isinstance(tags, list):
        tags = set(tags)
        
    is_accessory = False
    
    if (check_category(category, "Gia vị, nước chấm") or 
        check_category(category, "Nước giải khát") or 
        (check_category(category, "Đồ hộp") and any(k in name_vi for k in ["sweet", "syrup", "ngọt", "si rô", "đường", "condensed"]))):
        is_accessory = True
        
    if any(t in tags for t in ["is_powder", "is_processed", "is_condensed_milk", "is_cheese_butter", "allergen_milk", "is_dessert_snack"]):
        is_accessory = True
        
    if check_category(category, "Sữa và chế phẩm sữa") or check_category(category, "Sữa"):
        is_accessory = True
        
    # CHẶN TUYỆT ĐỐI BÁNH DẺO, BÁNH NƯỚNG, NƯỚC SỐT KHÔNG CHO LÀM MÓN ĂN CHÍNH
    keywords_accessory = [
        'sữa mẹ', 'bia', 'rượu', 'vodka', 'cognac', 'cocktail', 'cồn', 'kẹo', 'mứt', 
        'chè', 'bim bim', 'kem', 'thạch', 'mật ong', 'chocopie', 'bích quy', 
        'nước mắm', 'mắm tôm', 'mắm tép', 'xì dầu', 'magi', 'mỳ chính', 'bột canh', 
        'bột nêm', 'muối vừng', 'nước ướp', 'nước sốt', 'sốt', 'gói thuốc bắc', 'nước hàng', 
        'tương ngô', 'tương nếp', 'mẻ', 'giấm', 'bánh dẻo', 'bánh nướng', 'bánh trung thu'
    ]
    if any(kw in name_vi for kw in keywords_accessory):
        is_accessory = True
        
    is_raw = any(kw in name_vi for kw in ['sống', 'raw', 'chưa chế biến', 'gạo tẻ', 'gạo nếp'])
    has_cooking = any(kw in name_vi for kw in ['luộc', 'nướng', 'hấp', 'chín', 'hầm', 'chần', 'xào', 'rán', 'kho'])
    if is_raw and not has_cooking:
        is_accessory = True
        
    if is_accessory:
        return "ACCESSORY_CONDIMENT"
        
    # Nhóm tinh bột chín mặn chuẩn vị Việt
    keywords_carb = ['cơm', 'bún, tươi', 'bánh phở', 'nui, luộc', 'xôi', 'bánh mì', 'bánh mỳ', 'bánh cuốn', 'mỳ sợi', 'bánh khúc', 'bánh giò', 'bánh chưng', 'bánh đúc', 'bánh tẻ']
    if "role_carb" in tags or (any(kw in name_vi for kw in keywords_carb) and "bó xôi" not in name_vi):
        return "STAPLE_CARB"
        
    keywords_prep = ['luộc', 'xào', 'hấp', 'nộm', 'salad', 'tươi', 'muối sổi', 'dưa cải', 'chín', 'canh']
    if "role_fiber" in tags or (check_category(category, "Rau, quả, củ dùng làm rau") and any(kw in name_vi for kw in keywords_prep)):
        return "FIBER_SIDE"
        
    is_protein = False
    if "role_protein" in tags or "clean_protein" in tags:
        is_protein = True
    elif (check_category(category, "Thịt và sản phẩm chế biến") or 
          check_category(category, "Thủy sản và sản phẩm chế biến") or 
          check_category(category, "Trứng và sản phẩm chế biến")):
        keywords_protein_prep = ['luộc', 'xào', 'rán', 'kho', 'sốt', 'hầm', 'nướng', 'quay', 'hấp', 'chiên', 'chín', 'nấu', 'rang', 'chần']
        if any(kw in name_vi for kw in keywords_protein_prep):
            is_protein = True
                  
    if is_protein:
        if any(kw in name_vi for kw in ['ruốc', 'pate', 'ba tê', 'lạp xường', 'lạp sườn', 'khô', 'chả lụa', 'giò lụa', 'xúc xích']):
            return "ACCESSORY_CONDIMENT"
        return "MAIN_PROTEIN"
        
    return "ACCESSORY_CONDIMENT"


def is_single_bowl_meal(f: Dict[str, Any]) -> bool:
    name_vi = str(f.get("name_vi") or "").lower()
    tags = f.get("tags") or set()
    if "is_main_dish" in tags:
        return True
    keywords = ['phở', 'bún chả', 'bún nem', 'mỳ vằn thắn', 'mỳ sợi', 'bánh cuốn', 'cháo', 'xôi', 'bánh mì', 'bánh mỳ']
    return any(k in name_vi for k in keywords)


def is_offal_or_blood(f: Dict[str, Any]) -> bool:
    name_vi = str(f.get("name_vi") or "").lower()
    name_en = str(f.get("canonical_name_en") or "").lower()
    tags = f.get("tags") or set()
    if "is_blood" in tags or "tiết" in name_vi or "blood" in name_en or "blood" in name_vi:
        return True
    offal_kws_en = ['kidney', 'liver', 'stomach', 'intestine', 'gizzard']
    offal_kws_vi = ['bầu dục', 'gan', 'dạ dày', 'lòng', 'mề', 'phổi', 'óc', 'tủy']
    return (any(kw in name_en for kw in offal_kws_en) or 
            any(kw in name_vi for kw in offal_kws_vi))


def is_clean_protein_gym(f: Dict[str, Any]) -> bool:
    tags = f.get("tags") or set()
    name_en = str(f.get("canonical_name_en") or "").lower()
    name_vi = str(f.get("name_vi") or "").lower()
    if "clean_protein" in tags:
        return True
    gym_kws = ['chicken_breast', 'beef_tenderloin', 'pork_loin', 'egg', 'salmon', 'tuna', 'ức gà', 'thăn bò', 'thăn heo', 'trứng', 'cá hồi', 'cá ngừ']
    return any(kw in name_en or kw in name_vi for kw in gym_kws)


def is_gym_blacklisted(f: Dict[str, Any]) -> bool:
    """Check if food is blacklisted for gym profiles - fixed word boundary matching."""
    name_vi = str(f.get("name_vi") or "").lower()
    tokens = name_vi.split()
    blacklist_words = ['chè', 'mứt', 'kẹo', 'pate', 'lạp xường', 'lạp sườn', 'xúc xích', 'kem', 'sữa đặc', 'bơ', 'nước ngọt', 'tiết', 'lòng lợn', 'nội tạng', 'dồi']
    if any(w in tokens for w in blacklist_words):
        return True
    if "bim bim" in name_vi:
        return True
    return False


def clean_category(c: Any) -> str:
    c = str(c or "").lower().strip()
    nfkd_form = unicodedata.normalize('NFKD', c)
    return ''.join([ch for ch in nfkd_form if not unicodedata.combining(ch)]).replace('đ', 'd')


def get_max_serving_g(food: Dict[str, Any], is_gym: bool = False) -> float:
    tags = food.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(food)
        food["tags"] = tags
    role = classify_food(food)
    
    if "is_dried" in tags or "is_powder" in tags:
        return 30.0
    if "is_cheese_butter" in tags or "is_condensed_milk" in tags:
        return 50.0
    if "is_blood" in tags:
        return 150.0
    if "is_processed" in tags or "is_dessert_snack" in tags:
        return 150.0
    if role == "FIBER_SIDE":
        return 250.0
    if role == "STAPLE_CARB":
        return 300.0
    if role == "MAIN_PROTEIN":
        return 450.0 if is_gym else 350.0
    
    cat_clean = clean_category(food.get("category"))
    if cat_clean == "trai_cay":
        return 300.0
    return 300.0


def is_high_quality_protein(food: Dict[str, Any]) -> bool:
    tags = food.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(food)
        food["tags"] = tags
    return "clean_protein" in tags


def is_standalone_main_dish(f: Dict[str, Any]) -> bool:
    tags = f.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(f)
        f["tags"] = tags
    return "is_main_dish" in tags or is_single_bowl_meal(f)


def get_food_role(f: Dict[str, Any]) -> tuple[bool, bool, bool]:
    role = classify_food(f)
    return role == "MAIN_PROTEIN", role == "STAPLE_CARB", role == "FIBER_SIDE"