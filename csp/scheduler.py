"""Scheduler core utilizing backtracking and automated constraint relaxation."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import psycopg
from constraint import Problem

from .constraints import NutrientConstraints
from .objective import score_meal_plan


def translate_kaggle_food_name(name_en: str) -> str:
    """Smart translation heuristic for English food names (Kaggle).

    Splits by commas, removes unnecessary descriptions, and arranges words grammatically.
    """
    if not name_en:
        return ""

    import re

    # Unnecessary adjectives or technical descriptors to skip completely
    skip_phrases = {
        "meat only", "separable lean only", "separable lean and fat", "fluid",
        "without added vitamin a and vitamin d", "with bone", "bone-in",
        "without skin", "skinless", "moisture", "raw", "fresh", "dry", "dried",
        "powder", "powdered", "dehydrated", "imported", "processed", "all classes",
        "whole"
    }


    # Predefined Base + Part combinations for natural Vietnamese names
    predefined_combos = {
        ("chicken", "breast"): "ức gà",
        ("egg", "white"): "lòng trắng trứng",
        ("egg", "yolk"): "lòng đỏ trứng",
        ("beef", "ground"): "thịt bò xay",
        ("pork", "ground"): "thịt heo xay",
        ("pork", "loin"): "thịt thăn heo",
        ("beef", "loin"): "thịt thăn bò",
        ("pork", "shoulder"): "thịt nạc vai heo",
        ("beef", "tenderloin"): "thịt thăn nội bò",
        ("pork", "tenderloin"): "thịt thăn nội heo",
        ("potato", "sticks"): "khoai tây que chiên",
        ("jackfruit", "dried"): "mít sấy",
        ("banana", "dried"): "chuối sấy",
    }

    base_translations = {
        "chicken": "gà", "egg": "trứng", "beef": "thịt bò", "pork": "thịt heo",
        "duck": "vịt", "turkey": "gà tây", "shrimp": "tôm", "crab": "cua",
        "fish": "cá", "milk": "sữa", "rice": "cơm", "oats": "yến mạch",
        "salmon": "cá hồi", "tuna": "cá ngừ", "herring": "cá trích",
        "mackerel": "cá nục", "banana": "chuối", "cabbage": "rau cải",
        "spinach": "rau bó xôi", "broccoli": "súp lơ xanh", "potato": "khoai tây",
        "onion": "hành tây", "apple": "táo", "orange": "cam", "pear": "lê",
        "papaya": "đu đủ", "pineapple": "dứa", "watermelon": "dưa hấu",
        "mango": "xoài", "avocado": "bơ", "jackfruit": "mít", "cheese": "phô mai",
        "yogurt": "sữa chua", "pudding": "bánh pudding", "butter": "bơ",
        "blood": "tiết", "pig": "lợn", "fruit": "trái cây", "vegetable": "rau",
        "salad": "xà lách",
        "cod": "cá tuyết", "catfish": "cá trê", "sardine": "cá mòi", "tilapia": "cá rô phi"
    }

    part_translations = {
        "breast": "ức", "white": "lòng trắng", "yolk": "lòng đỏ",
        "loin": "thịt thăn", "tenderloin": "thịt thăn nội", "ground": "xay",
        "fillet": "phi lê", "skin": "da", "liver": "gan", "heart": "tim",
        "kidney": "cật", "gizzard": "mề", "shoulder": "nạc vai",
        "thigh": "thịt đùi", "wing": "cánh", "drumstick": "tỏi đùi"
    }

    prep_translations = {
        "boiled": "luộc", "steamed": "hấp", "fried": "chiên",
        "grilled": "nướng", "roasted": "quay", "baked": "nướng",
        "canned": "đóng hộp",
        "smoked": "xông khói", "roast": "quay", "bake": "nướng",
        "broil": "nướng", "broiled": "nướng", "grill": "nướng",
        "stew": "hầm", "stewed": "hầm", "cooked": "luộc"
    }

    other_translations = {
        "sweet": "ngọt", "salted": "muối", "spicy": "cay",
        "lowfat": "ít béo", "nonfat": "không béo"
    }


    # Split name by commas and clean each segment
    segments = [s.strip().lower() for s in name_en.split(",")]
    cleaned_segments = []
    
    # Track if it has milkfat percentage or similar special terms
    fat_pct = ""
    for segment in segments:
        if segment in skip_phrases:
            continue
        # Check for pattern like "3.25% milkfat" or "1% fat"
        if "milkfat" in segment or "fat" in segment:
            match = re.search(r'(\d+(?:\.\d+)?%)', segment)
            if match:
                fat_pct = f"{match.group(1)} béo"
                continue
        cleaned_segments.append(segment)

    if not cleaned_segments:
        return ""

    # Parse first segment into words to identify base food and immediate parts
    first_seg_words = cleaned_segments[0].split()
    base_word = ""
    part_word = ""

    # Identify base word (e.g. "chicken" in "chicken breast")
    for w in first_seg_words:
        if w in base_translations:
            base_word = w
            break

    # If first segment has a modifier (e.g., "chicken breast"), find the modifier
    for w in first_seg_words:
        if w != base_word and w in part_translations:
            part_word = w
            break

    # If first segment is just base, look at the second segment for part/modifier
    if not part_word and len(cleaned_segments) > 1:
        second_seg_words = cleaned_segments[1].split()
        for w in second_seg_words:
            if w in part_translations:
                part_word = w
                break

    # Check predefined combos
    translated_main = ""
    if base_word and part_word and (base_word, part_word) in predefined_combos:
        translated_main = predefined_combos[(base_word, part_word)]
    else:
        # Build translation grammatically
        translated_base = base_translations.get(base_word, "") if base_word else ""
        translated_part = part_translations.get(part_word, "") if part_word else ""
        
        if translated_part and translated_base:
            translated_main = f"{translated_part} {translated_base}"
        elif translated_base:
            translated_main = translated_base
        else:
            # Fallback to translate segment word-by-word
            words = []
            for s in cleaned_segments[:2]:
                for w in s.split():
                    tr = base_translations.get(w) or part_translations.get(w) or prep_translations.get(w) or other_translations.get(w) or w
                    words.append(tr)
            translated_main = " ".join(words)

    # Add other modifiers like preparation method or fat percentage
    modifiers = []
    # Check all segments for preparation methods or other known words
    for idx, segment in enumerate(cleaned_segments):
        for w in segment.split():
            if idx == 0:
                if w == base_word or w == part_word:
                    continue
            if w in prep_translations:
                modifiers.append(prep_translations[w])
            elif w in other_translations:
                modifiers.append(other_translations[w])

    if fat_pct:
        modifiers.append(fat_pct)

    res = translated_main
    if modifiers:
        res = f"{translated_main} {' '.join(modifiers)}"

    # Clean up and capitalize
    res = re.sub(r'\s+', ' ', res).strip()
    raw_defaults = {
        "cá": "Cá hấp",
        "gà": "Thịt gà luộc",
        "thịt bò": "Thịt bò xào",
        "thịt heo": "Thịt heo luộc",
        "thịt vịt": "Thịt vịt luộc",
    }
    if res.lower() in raw_defaults:
        return raw_defaults[res.lower()]
    return res.capitalize()



def _normalize_for_matching(text: str) -> str:
    import unicodedata
    import re
    if not text:
        return ""
    text = unicodedata.normalize('NFKC', text).lower()
    # Replace punctuation with spaces
    for char in ".,()[]{}/\\-_+*?!:;\"'":
        text = text.replace(char, " ")
    # Collapse multiple spaces
    return re.sub(r'\s+', ' ', text).strip()


def get_dynamic_tags(food: Dict[str, Any]) -> set[str]:
    """Dynamically generate tags for a food item using rules (fallback for tests/mock data)."""
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

    milk_kws = ["sữa", "milk", "bơ", "butter", "cheese", "phô mai", "pho mai", "yogurt", "sữa chua", "whey", "lactose", "váng sữa", "sữa đặc"]
    if has_any(milk_kws):
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
        if not has_any_name(["chè", "che ", "mận"]):
            tags.add("role_carb")

    fiber_cats = ["rau_cu", "trai_cay", "rau củ", "trái cây", "rau"]
    fiber_kws = ["cabbage", "cải", "vegetable", "rau", "salad", "xà lách", "onion", "hành", "fruit", "trái cây", "banana", "chuối", "muống", "bó xôi", "súp lơ", "nấm", "quả", "táo", "cam", "nho", "xoài"]
    if any(n_cat == _normalize_for_matching(c) for c in fiber_cats) or has_any(fiber_kws):
        tags.add("role_fiber")

    # 3. Clean protein
    exclude_clean_kws = [
        "vặt", "tráng miệng", "bánh", "kẹo", "chè", "kem", "chiên", "rán",
        "hộp", "canned", "khô", "dried", "bột", "pate", "lạp xưởng", "xúc xích",
        "béo", "mỡ", "da", "đường"
    ]
    clean_protein_kws = [
        "ức gà", "uc ga", "chicken breast", "thịt bò", "thit bo", "beef",
        "trứng", "egg", "cá hồi", "salmon", "cá ngừ", "tuna", "thịt lợn", "thịt heo", "pork",
        "vịt", "duck", "tôm", "shrimp", "cua", "crab", "thịt nạc", "thịt gia cầm"
    ]
    if "role_protein" in tags:
        if not has_any(exclude_clean_kws):
            if has_any(clean_protein_kws):
                tags.add("clean_protein")

    # 4. Portion limits (Name-only matching)
    if has_any_name(["khô", "sấy", "dried"]):
        tags.add("is_dried")
    if has_any_name(["bột", "powder", "whey"]):
        tags.add("is_powder")
    if has_any_name(["hộp", "canned", "sốt cà chua", "pate", "lạp xưởng", "xúc xích"]):
        tags.add("is_processed")
    if has_any_name(["phô mai", "pho mai", "cheese", "bơ", "butter"]):
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


def get_max_serving_g(food: Dict[str, Any], is_gym: bool = False) -> float:
    """Get the scientific maximum portion weight limit (in grams) for a food item."""
    tags = food.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(food)
        food["tags"] = tags
        
    if "is_dried" in tags or "is_powder" in tags:
        return 30.0
    if "is_cheese_butter" in tags or "is_condensed_milk" in tags:
        return 50.0
    if "is_blood" in tags:
        return 150.0
    if "is_processed" in tags or "is_dessert_snack" in tags:
        return 150.0
    if "role_carb" in tags:
        return 300.0
    if "role_protein" in tags:
        return 450.0 if is_gym else 350.0
    if "role_fiber" in tags:
        return 250.0
    return 300.0


def is_high_quality_protein(food: Dict[str, Any]) -> bool:
    """Check if a food item is a high-quality protein source for muscle growth."""
    tags = food.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(food)
        food["tags"] = tags
    return "clean_protein" in tags


def clean_category(c) -> str:
    import unicodedata
    c = str(c or "").lower().strip()
    nfkd_form = unicodedata.normalize('NFKD', c)
    return ''.join([ch for ch in nfkd_form if not unicodedata.combining(ch)]).replace('đ', 'd')


def is_standalone_main_dish(f: Dict[str, Any]) -> bool:
    tags = f.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(f)
        f["tags"] = tags
    return "is_main_dish" in tags


def get_food_role(f: Dict[str, Any]) -> tuple[bool, bool, bool]:
    tags = f.get("tags") or set()
    if not tags:
        tags = get_dynamic_tags(f)
        f["tags"] = tags
    return "role_protein" in tags, "role_carb" in tags, "role_fiber" in tags





class MealScheduler:
    """Ties together constraints and solver logic to produce 7-day personal meal plans."""

    def __init__(
        self,
        user_profile: Dict[str, Any],
        available_foods: List[Dict[str, Any]] | None = None,
        db_url: str | None = None,
    ) -> None:
        self.user = user_profile
        self.db_url = db_url if db_url is not None else os.getenv("DATABASE_URL")
        
        # Smart detection of Gym target
        self.is_gym = (
            float(self.user.get("daily_calorie_target") or 0.0) >= 2800.0
            or str(self.user.get("goal") or "").lower() == "gym"
            or "gym" in str(self.user.get("user_message") or "").lower()
        )
        
        self.foods = available_foods or self._load_foods()
        
        # Post-load tag correction: fix foods with incorrect pre-computed tags from CSV/DB
        for f in self.foods:
            name_vi = str(f.get("name_vi") or "").lower()
            tags = f.get("tags")
            if tags is None:
                tags = set()
                f["tags"] = tags
            elif isinstance(tags, str):
                tags = {t.strip().lower() for t in tags.split(",") if t.strip()}
                f["tags"] = tags
            
            # "Mận cơm" is a plum fruit, NOT a carb source — strip role_carb
            if "mận" in name_vi and "role_carb" in tags:
                tags.discard("role_carb")
                if "role_fiber" not in tags:
                    tags.add("role_fiber")
        
        # Gán trường max_serving_g cho từng món ăn
        for f in self.foods:
            f["max_serving_g"] = get_max_serving_g(f, self.is_gym)
            
        self.food_by_id = {int(f["food_id"]): f for f in self.foods}

    def _load_foods(self) -> List[Dict[str, Any]]:
        """Load candidate foods from database, with robust fallback to sample dataset and offline CSV."""
        foods_list: List[Dict[str, Any]] = []
        if self.db_url:
            try:
                # Load tags first
                tag_map = {}
                try:
                    with psycopg.connect(self.db_url) as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                SELECT m.food_id, t.tag_code
                                FROM food_tag_mapping m
                                JOIN food_tags t ON m.tag_id = t.tag_id;
                                """
                            )
                            for fid, code in cur.fetchall():
                                tag_map.setdefault(int(fid), set()).add(code)
                except Exception as tag_exc:
                    logging.getLogger(__name__).warning("Could not load food tags from DB: %s", tag_exc)

                query = """
                    SELECT 
                        f.food_id, f.canonical_key, f.canonical_name_en, f.name_vi,
                        n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g,
                        COALESCE(p.price_100g_vnd, 15000) AS price_100g,
                        g.group_code AS category,
                        f.source_name, f.source_priority
                    FROM foods f
                    JOIN food_nutrients n ON f.food_id = n.food_id
                    JOIN food_groups g ON f.food_group_id = g.food_group_id
                    LEFT JOIN food_price_estimates p ON f.food_id = p.food_id
                    WHERE f.is_active = TRUE;
                """
                with psycopg.connect(self.db_url) as conn:
                    with conn.cursor() as cur:
                        cur.execute(query)
                        for row in cur.fetchall():
                            fid, key, name_en, name_vi, cal, prot, fat, carb, price, category, src_name, src_priority = row
                            foods_list.append({
                                "food_id": int(fid),
                                "canonical_key": key,
                                "canonical_name_en": name_en,
                                "name_vi": name_vi,
                                "calories": float(cal or 0),
                                "protein": float(prot or 0),
                                "fat": float(fat or 0),
                                "carbs": float(carb or 0),
                                "cost_vnd_100g": float(price or 15000),
                                "category": category,
                                "source_name": src_name,
                                "source_priority": int(src_priority or 1),
                                "tags": tag_map.get(int(fid), set()),
                            })
                return foods_list
            except Exception as exc:
                logging.getLogger(__name__).warning("Could not load foods from DB: %s. Trying offline CSV.", exc)

        # Robust offline CSV + JSON prices database fallback
        import os
        import csv
        import json
        csv_path = "data/raw/final_nutrients_structured.csv"
        prices_path = "data/seeded_prices.json"
        
        if os.path.exists(csv_path):
            try:
                logging.getLogger(__name__).info("Loading foods from offline CSV: %s", csv_path)
                
                prices_map = {}
                if os.path.exists(prices_path):
                    with open(prices_path, encoding="utf-8") as pf:
                        price_data = json.load(pf)
                        for item in price_data.get("items", []):
                            key = str(item.get("canonical_key") or "").lower().strip()
                            name = str(item.get("name_vi") or "").lower().strip()
                            price = float(item.get("price_100g") or 15000.0)
                            if key:
                                prices_map[key] = price
                            if name:
                                prices_map[name] = price
                
                with open(csv_path, encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    idx = 1
                    for row in reader:
                        key = row.get("canonical_key") or ""
                        name_vi = row.get("name_vi") or ""
                        name_en = row.get("canonical_name_en") or row.get("name_en") or ""
                        cal = row.get("nang_luong_kcal") or 0.0
                        prot = row.get("chat_dam_g") or 0.0
                        fat = row.get("chat_beo_g") or 0.0
                        carb = row.get("chat_bot_duong_g") or 0.0
                        category = row.get("category") or "other"
                        src_name = row.get("source") or "NIN"
                        src_priority = row.get("source_priority") or 1
                        tags_str = row.get("tags") or ""
                        row_tags = {t.strip().lower() for t in tags_str.split(",") if t.strip()}
                        
                        price = prices_map.get(key.lower().strip()) or prices_map.get(name_vi.lower().strip()) or 15000.0
                        
                        foods_list.append({
                            "food_id": idx,
                            "canonical_key": key,
                            "canonical_name_en": name_en,
                            "name_vi": name_vi,
                            "calories": float(cal or 0.0),
                            "protein": float(prot or 0.0),
                            "fat": float(fat or 0.0),
                            "carbs": float(carb or 0.0),
                            "cost_vnd_100g": float(price),
                            "category": category,
                            "source_name": src_name,
                            "source_priority": int(src_priority or 1),
                            "tags": row_tags,
                        })
                        idx += 1
                return foods_list
            except Exception as exc:
                logging.getLogger(__name__).warning("Could not load foods from offline CSV: %s. Using hardcoded fallback.", exc)

        # Fallback to absolute minimum sample database if CSV doesn't exist
        return [
            {"food_id": 1, "canonical_key": "uc_ga", "canonical_name_en": "Chicken Breast", "name_vi": "ức gà", "calories": 165, "protein": 31, "fat": 3.6, "carbs": 0, "cost_vnd_100g": 15000},
            {"food_id": 2, "canonical_key": "trung", "canonical_name_en": "Egg", "name_vi": "trứng", "calories": 155, "protein": 13, "fat": 11, "carbs": 1.1, "cost_vnd_100g": 4000},
            {"food_id": 3, "canonical_key": "yen_mach", "canonical_name_en": "Oats", "name_vi": "yến mạch", "calories": 389, "protein": 16.9, "fat": 6.9, "carbs": 66.3, "cost_vnd_100g": 10000},
            {"food_id": 4, "canonical_key": "com_trang", "canonical_key_vi": "cơm trắng", "canonical_name_en": "White Rice", "name_vi": "cơm trắng", "calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28, "cost_vnd_100g": 1800},
            {"food_id": 5, "canonical_key": "thit_bo", "canonical_name_en": "Beef", "name_vi": "thịt bò", "calories": 250, "protein": 26, "fat": 15, "carbs": 0, "cost_vnd_100g": 25000},
            {"food_id": 6, "canonical_key": "ca_hoi", "canonical_name_en": "Salmon", "name_vi": "cá hồi", "calories": 208, "protein": 20, "fat": 13, "carbs": 0, "cost_vnd_100g": 45000},
            {"food_id": 7, "canonical_key": "sua_tuoi", "canonical_name_en": "Milk", "name_vi": "sữa tươi", "calories": 60, "protein": 3.2, "fat": 3.25, "carbs": 4.8, "cost_vnd_100g": 3000},
            {"food_id": 8, "canonical_key": "chuoi", "canonical_name_en": "Banana", "name_vi": "chuối", "calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 22.8, "cost_vnd_100g": 2000},
            {"food_id": 9, "canonical_key": "rau_cai", "canonical_name_en": "Cabbage", "name_vi": "rau cải", "calories": 25, "protein": 1.3, "fat": 0.1, "carbs": 5.8, "cost_vnd_100g": 1500},
            {"food_id": 10, "canonical_key": "vit", "canonical_name_en": "Duck", "name_vi": "thịt vịt", "calories": 337, "protein": 19, "fat": 28, "carbs": 0, "cost_vnd_100g": 18000},
        ]

    def solve_with_relaxation(self, max_attempts: int = 4) -> Dict[str, Any]:
        """Solver orchestration wrapping the auto-relaxation loops.

        Attempts to solve CSP, increasing tolerances dynamically if no solution found.
        """
        constraints = NutrientConstraints(
            daily_calorie_target=float(self.user.get("daily_calorie_target") or 2000.0),
            calorie_tolerance_pct=0.12,
            macro_ratios=self.user.get("macro_ratios"),
            macro_tolerance_pct=0.12,
            allergies=self.user.get("allergies"),
            budget_vnd_max=self.user.get("budget_vnd_max"),
            max_food_occurrences_per_week=2,
        )


        # Extract only candidate subset if provided to keep domain small and extremely fast
        domain_foods = self.foods
        
        if constraints.allergies:
            domain_foods = [f for f in domain_foods if constraints.check_allergies([f])]
        
        # Pre-filter junk/unwanted foods for Gym users before stratified sampling so we don't waste slots!
        if self.is_gym:
            gym_filtered = []
            for f in domain_foods:
                name_vi = str(f.get("name_vi") or "").lower()
                name_en = str(f.get("canonical_name_en") or "").lower()
                cat = str(f.get("category") or "").lower()
                
                # Check for junk / processed / sugary foods
                is_junk = any(k in name_vi or k in name_en or k in cat for k in (
                    "chè", "che ", "bánh ngọt", "banh ngọt", "bánh kẹo", "banh keo", "kẹo", 
                    "mứt", "bim bim", "pate", "lạp xưởng", "xúc xích", "kem", "sữa đặc", 
                    "bơ", "nước ngọt", "soda", "muối ớt", "bánh mỳ nướng", "rán", "chiên", 
                    "tiết", "lòng lợn", "nội tạng", "dồi", "lòng vịt", "lòng gà"
                ))
                
                # Exclude low quality proteins
                is_p, _, _ = get_food_role(f)
                if is_p and not is_high_quality_protein(f):
                    is_junk = True
                    
                if not is_junk:
                    gym_filtered.append(f)
            domain_foods = gym_filtered

        if self.user.get("candidates"):
            candidates_spec = self.user["candidates"]
            # Accept either a list of IDs or names
            candidate_ids = set()
            for cand in candidates_spec:
                if isinstance(cand, dict) and cand.get("id") is not None:
                    candidate_ids.add(int(cand["id"]))
                elif isinstance(cand, int):
                    candidate_ids.add(cand)

            if candidate_ids:
                domain_foods = [f for f in domain_foods if int(f["food_id"]) in candidate_ids]

        if not domain_foods:
            # Fallback to all foods if domain is empty to guarantee a solution
            domain_foods = self.foods

        # Cap the domain size to prevent python-constraint backtracking solver from hanging
        # when running on the entire database (9609 foods).
        MAX_DOMAIN_SIZE = 350
        if len(domain_foods) > MAX_DOMAIN_SIZE:
            by_category = {}
            for f in domain_foods:
                cat = str(f.get("category") or "other").lower()
                by_category.setdefault(cat, []).append(f)
            
            selected = []
            category_lists = []
            # Sort each category list so that foods with source_priority=1 (NIN) come first!
            for cat_list in by_category.values():
                cat_list.sort(key=lambda x: int(x.get("source_priority") or 1))
                category_lists.append(cat_list)
            
            if category_lists:
                idx = 0
                while len(selected) < MAX_DOMAIN_SIZE:
                    added_any = False
                    for cat_list in category_lists:
                        if idx < len(cat_list):
                            selected.append(cat_list[idx])
                            added_any = True
                            if len(selected) >= MAX_DOMAIN_SIZE:
                                break
                    if not added_any:
                        break
                    idx += 1
                domain_foods = selected
            else:
                domain_foods = domain_foods[:MAX_DOMAIN_SIZE]

        attempt = 1
        tolerance_multiplier = 1.0

        while attempt <= max_attempts:
            logging.getLogger(__name__).info(
                "CSP Solve Attempt %s/%s (multiplier=%.2f)", attempt, max_attempts, tolerance_multiplier
            )
            result = self._solve(domain_foods, constraints, tolerance_multiplier)
            if result["feasible"]:
                result["relaxation_attempts"] = attempt
                return result

            # Relax constraints for next attempt
            tolerance_multiplier += 0.25
            attempt += 1

        return {
            "status": "infeasible",
            "feasible": False,
            "meal_plan": [],
            "relaxation_attempts": max_attempts,
        }

    def _get_meal_plan_for_solution(
        self,
        sol: Dict[str, int],
        constraints: NutrientConstraints,
        tolerance_multiplier: float,
        all_carbs: List[Dict[str, Any]],
        all_proteins: List[Dict[str, Any]],
        all_fibers: List[Dict[str, Any]],
        all_snacks: List[Dict[str, Any]],
        day_excluded_ids: Set[int] | None = None,
    ) -> List[Dict[str, Any]]:
        # Helper to find a safe complementary item from a pool
        def get_complementary(pool, excluded_ids=None):
            if excluded_ids is None:
                excluded_ids = set()
            
            # 1. Try to find an item that is NOT in excluded_ids AND NOT in day_excluded_ids
            for f in pool:
                fid = int(f["food_id"])
                if fid in excluded_ids:
                    continue
                if day_excluded_ids and fid in day_excluded_ids:
                    continue
                if not constraints.check_allergies([f]):
                    continue
                return f
                
            # 2. Fallback to just excluding things in the current day's meals
            for f in pool:
                fid = int(f["food_id"])
                if fid in excluded_ids:
                    continue
                if not constraints.check_allergies([f]):
                    continue
                return f
                
            return pool[0]

        exclude_snacks = self.user.get("exclude_snacks", False)

        # 1. Fetch core foods
        b_food = self.food_by_id[sol["breakfast"]]
        l_food = self.food_by_id[sol["lunch"]]
        s_food = None if exclude_snacks else self.food_by_id.get(sol.get("snack"))
        d_food = self.food_by_id[sol["dinner"]]

        # Strict snack restriction: main meals cannot be snacks or desserts
        main_meal_pairs = [("breakfast", b_food), ("lunch", l_food), ("dinner", d_food)]
        for slot, food in main_meal_pairs:
            cat = str(food.get("category") or "").lower()
            if any(k in cat for k in ("đồ_ăn_vặt", "tráng_miệng", "bánh_kẹo", "bánh_ngọt")):
                raise ValueError("Snacks/desserts are forbidden in main meals")

        # 2. Match complementary components to build multi-component meals if we have enough food variety
        is_rich_db = len(all_carbs) >= 1 and len(all_proteins) >= 1 and len(all_fibers) >= 1
        
        # Log pool sizes for debugging
        logging.getLogger(__name__).debug(
            "Food pools: carbs=%d, proteins=%d, fibers=%d, snacks=%d, is_rich=%s",
            len(all_carbs), len(all_proteins), len(all_fibers), len(all_snacks), is_rich_db
        )

        if is_rich_db:
            # Track Carb, Protein, Veg statuses for Breakfast, Lunch, Dinner
            has_carb = {"breakfast": False, "lunch": False, "dinner": False}
            has_protein = {"breakfast": False, "lunch": False, "dinner": False}
            has_veg = {"breakfast": False, "lunch": False, "dinner": False}
            
            # Populate based on core foods
            for slot, food in main_meal_pairs:
                is_p, is_c, is_f = get_food_role(food)
                
                if is_standalone_main_dish(food):
                    has_carb[slot] = True
                    has_protein[slot] = True
                    has_veg[slot] = True
                else:
                    if is_p: has_protein[slot] = True
                    if is_c: has_carb[slot] = True
                    if is_f: has_veg[slot] = True

            # Build list of extra components to add
            extra_components = []
            
            # Enforce Protein in every main meal
            for slot, food in main_meal_pairs:
                if not is_standalone_main_dish(food) and not has_protein[slot]:
                    extra_components.append((slot, "protein"))

            # Enforce Carb in every main meal
            for slot, food in main_meal_pairs:
                if not is_standalone_main_dish(food) and not has_carb[slot]:
                    extra_components.append((slot, "carb"))

            # Enforce Veg in Lunch and Dinner
            for slot, food in [("lunch", l_food), ("dinner", d_food)]:
                if not is_standalone_main_dish(food) and not has_veg[slot]:
                    extra_components.append((slot, "fiber"))

            # Build components list
            components = []
            components.append({"slot": "breakfast", "food": b_food, "role": "core"})
            components.append({"slot": "lunch", "food": l_food, "role": "core"})
            if not exclude_snacks and s_food:
                components.append({"slot": "snack", "food": s_food, "role": "snack"})
            components.append({"slot": "dinner", "food": d_food, "role": "core"})

            # Add complementary components if the core food is NOT a standalone main dish
            excluded_ids = set()
            
            # Filter protein pool for gym
            if self.is_gym:
                gym_proteins = [f for f in all_proteins if is_high_quality_protein(f)]
                comp_proteins_pool = gym_proteins if gym_proteins else all_proteins
            else:
                comp_proteins_pool = all_proteins

            for slot, role in extra_components:
                core_food = b_food if slot == "breakfast" else (l_food if slot == "lunch" else d_food)
                if is_standalone_main_dish(core_food):
                    continue # Stands completely alone!
                
                if role == "carb":
                    comp_food = get_complementary(all_carbs, excluded_ids=excluded_ids)
                    components.append({"slot": slot, "food": comp_food, "role": "carb"})
                    excluded_ids.add(comp_food["food_id"])
                elif role == "protein":
                    comp_food = get_complementary(comp_proteins_pool, excluded_ids=excluded_ids)
                    components.append({"slot": slot, "food": comp_food, "role": "protein"})
                    excluded_ids.add(comp_food["food_id"])
                elif role == "fiber":
                    comp_food = get_complementary(all_fibers, excluded_ids=excluded_ids)
                    components.append({"slot": slot, "food": comp_food, "role": "fiber"})
                    excluded_ids.add(comp_food["food_id"])
        else:
            components = [
                {"slot": "breakfast", "food": b_food, "role": "core"},
                {"slot": "lunch", "food": l_food, "role": "core"},
            ]
            if not exclude_snacks and s_food:
                components.append({"slot": "snack", "food": s_food, "role": "snack"})
            components.append({"slot": "dinner", "food": d_food, "role": "core"})

        # Check allergy constraint on all components
        if not constraints.check_allergies([c["food"] for c in components]):
            raise ValueError("Allergy constraint violated")

        # Enforce Gym high quality protein constraint on lunch/dinner meals
        if self.is_gym:
            # Check lunch
            lunch_has_hq = any(is_high_quality_protein(c["food"]) for c in components if c["slot"] == "lunch")
            # Check dinner
            dinner_has_hq = any(is_high_quality_protein(c["food"]) for c in components if c["slot"] == "dinner")
            
            if not lunch_has_hq or not dinner_has_hq:
                raise ValueError("Gym menu must contain high quality protein in both lunch and dinner")

        # Optimize weights using micro-grid search to perfectly align calories and macro ratios
        p_ratio = constraints.macro_ratios.get("protein", 0.3)
        c_ratio = constraints.macro_ratios.get("carbs", 0.4)
        f_ratio = constraints.macro_ratios.get("fat", 0.3)

        # Scale portion weights dynamically for high-calorie dieters (e.g. gym goers eating larger portions)
        is_high_calorie = constraints.daily_calorie_target >= 2800.0
        w_prot_space = [75.0, 100.0, 150.0, 200.0, 250.0, 300.0, 400.0, 500.0] if is_high_calorie else [50.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0, 300.0]
        w_crb_space = [75.0, 100.0, 150.0, 200.0, 250.0, 300.0, 400.0, 500.0] if is_high_calorie else [50.0, 75.0, 100.0, 125.0, 150.0, 200.0, 250.0, 300.0]
        w_fix_space = [30.0, 50.0, 80.0, 100.0, 150.0, 200.0] if is_high_calorie else [30.0, 50.0, 80.0, 100.0, 150.0]

        best_w_protein = 150.0
        best_w_carb = 150.0
        best_w_fixed = 100.0
        min_error = float("inf")
        
        for w_prot in w_prot_space:
            for w_crb in w_crb_space:
                for w_fix in w_fix_space:
                    skip_combo = False
                    total_cal = 0.0
                    total_p = 0.0
                    total_f = 0.0
                    total_c = 0.0
                    meal_cals = {"breakfast": 0.0, "lunch": 0.0, "dinner": 0.0, "snack": 0.0}
                    
                    for comp in components:
                        f = comp["food"]
                        slot = comp["slot"]
                        
                        if slot == "snack":
                            w = w_fix
                        else:
                            is_p, is_c, is_f = get_food_role(f)
                            if is_standalone_main_dish(f):
                                w = w_prot
                            elif is_c:
                                w = w_crb
                            elif is_p:
                                w = w_prot
                            else:
                                w = w_fix
                        
                        # Serving Size Cap constraint
                        max_w = f.get("max_serving_g") or get_max_serving_g(f, self.is_gym)
                        if w > max_w:
                            skip_combo = True
                            break
                        
                        item_cal = float(f.get("calories") or f.get("energy_kcal") or 0.0) * (w / 100.0)
                        total_cal += item_cal
                        meal_cals[slot] += item_cal
                        
                        total_p += float(f.get("protein") or f.get("protein_g") or 0.0) * (w / 100.0)
                        total_f += float(f.get("fat") or f.get("fat_g") or 0.0) * (w / 100.0)
                        total_c += float(f.get("carbs") or f.get("carbs_g") or 0.0) * (w / 100.0)
                        
                    if skip_combo:
                        continue
                        
                    cal_error = abs(total_cal - constraints.daily_calorie_target) / constraints.daily_calorie_target
                    
                    # Calorie distribution penalty
                    b_pct = meal_cals["breakfast"] / total_cal if total_cal > 0 else 0.0
                    l_pct = meal_cals["lunch"] / total_cal if total_cal > 0 else 0.0
                    d_pct = meal_cals["dinner"] / total_cal if total_cal > 0 else 0.0
                    
                    dist_error = 0.0
                    if not (0.15 <= b_pct <= 0.35):
                        dist_error += abs(b_pct - 0.25)
                    if not (0.25 <= l_pct <= 0.45):
                        dist_error += abs(l_pct - 0.35)
                    if not (0.25 <= d_pct <= 0.45):
                        dist_error += abs(d_pct - 0.35)
                        
                    cal_error += dist_error * 2.0
                    
                    total_mass = total_p + total_f + total_c
                    if total_mass > 0:
                        macro_error = (
                            abs((total_p / total_mass) - p_ratio) +
                            abs((total_f / total_mass) - f_ratio) +
                            abs((total_c / total_mass) - c_ratio)
                        )
                    else:
                        macro_error = 1.0
                        
                    error = cal_error + macro_error
                    if error < min_error:
                        min_error = error
                        best_w_protein = w_prot
                        best_w_carb = w_crb
                        best_w_fixed = w_fix

        weights = {}
        for comp in components:
            f = comp["food"]
            slot = comp["slot"]
            if slot == "snack":
                w = best_w_fixed
            else:
                is_p, is_c, is_f = get_food_role(f)
                if is_standalone_main_dish(f):
                    w = best_w_protein
                elif is_c:
                    w = best_w_carb
                elif is_p:
                    w = best_w_protein
                else:
                    w = best_w_fixed
            weights[f["food_id"]] = w

        # Build scaled components
        scaled_components = []
        for comp in components:
            f = comp["food"]
            w = weights[f["food_id"]]
            scaled = {
                **f,
                "weight_g": w,
                "calories": float(f.get("calories") or f.get("energy_kcal") or 0.0) * (w / 100.0),
                "protein": float(f.get("protein") or f.get("protein_g") or 0.0) * (w / 100.0),
                "fat": float(f.get("fat") or f.get("fat_g") or 0.0) * (w / 100.0),
                "carbs": float(f.get("carbs") or f.get("carbs_g") or 0.0) * (w / 100.0),
                "cost_vnd": float(f.get("cost_vnd_100g") or 15000) * (w / 100.0),
            }
            scaled_components.append({"slot": comp["slot"], "scaled_food": scaled})

        # Assemble meal slots
        day_meals = []
        slots_to_generate = ["breakfast", "lunch", "dinner"] if exclude_snacks else ["breakfast", "lunch", "snack", "dinner"]
        for slot in slots_to_generate:
            slot_comps = [sc["scaled_food"] for sc in scaled_components if sc["slot"] == slot]
            if not slot_comps:
                continue
            
            names_vi = []
            for sc in slot_comps:
                display_name = sc.get("name_vi")
                if not display_name:
                    display_name = translate_kaggle_food_name(sc.get("canonical_name_en") or "")
                    if display_name:
                        import re
                        display_name = re.sub(r'(?i)\s+(sấy khô|khô|sấy|nguyên chất)\b', '', display_name)
                    if display_name and display_name.lower() != (sc.get("canonical_name_en") or "").lower():
                        display_name = f"{display_name} (Kaggle - Dịch)"
                else:
                    import re
                    display_name = re.sub(r'(?i)\s+(sấy khô|khô|sấy|nguyên chất)\b', '', display_name)
                    display_name = f"{display_name} (Món Việt - NIN)"
                
                names_vi.append(f"{display_name} ({int(sc['weight_g'])}g)")

            combined_name = " + ".join(names_vi)
            core_id = slot_comps[0]["food_id"]

            day_meals.append({
                "meal_type": slot,
                "food_id": core_id,
                "name": combined_name,
                "canonical_name_en": slot_comps[0].get("canonical_name_en", ""),
                "name_vi": slot_comps[0].get("name_vi", ""),
                "category": slot_comps[0].get("category", ""),
                "cost_vnd_100g": sum(sc["cost_vnd"] for sc in slot_comps),
                "calories": sum(sc["calories"] for sc in slot_comps),
                "protein": sum(sc["protein"] for sc in slot_comps),
                "fat": sum(sc["fat"] for sc in slot_comps),
                "carbs": sum(sc["carbs"] for sc in slot_comps),
                "component_food_ids": [sc["food_id"] for sc in slot_comps],
            })

        return day_meals

    def _solve(self, domain_foods: List[Dict[str, Any]], constraints: NutrientConstraints, tolerance_multiplier: float) -> Dict[str, Any]:
        """Optimized CSP Solver using python-constraint.

        Solves daily meal plans first, then schedules them weekly with diversity checks.
        """
        # Partition all self.foods into Carb, Protein, Fiber, and Snack pools
        all_carbs = []
        all_proteins = []
        all_fibers = []
        all_snacks = []
        for f in self.foods:
            tags = f.get("tags") or set()
            if not tags:
                tags = get_dynamic_tags(f)
                f["tags"] = tags

            if self.is_gym:
                # exclude junk/unwanted foods for Gym
                if "is_dessert_snack" in tags or "is_processed" in tags or "is_condensed_milk" in tags or "is_cheese_butter" in tags or "is_dried" in tags or "is_powder" in tags:
                    if not ("is_powder" in tags and "role_protein" in tags): # Allow protein powder
                        continue

            if "role_protein" in tags:
                all_proteins.append(f)
            if "role_carb" in tags:
                all_carbs.append(f)
            if "role_fiber" in tags:
                all_fibers.append(f)
                
            # Snack pool: fruit, dairy, nuts
            cat_clean = clean_category(f.get("category"))
            if any(c in cat_clean for c in ("trai_cay", "sua_che_pham", "hat", "do_an_vat")) or "is_dessert_snack" in tags:
                all_snacks.append(f)

        if not all_carbs: all_carbs = [f for f in self.foods if f["food_id"] in (3, 4)]
        if not all_proteins: all_proteins = [f for f in self.foods if f["food_id"] in (1, 2, 5, 6)]
        if not all_fibers: all_fibers = [f for f in self.foods if f["food_id"] == 9]
        if not all_snacks: all_snacks = [f for f in self.foods if f["food_id"] in (7, 8)]

        def carb_priority_rank(x: Dict[str, Any]) -> int:
            name = str(x.get("name_vi") or x.get("canonical_name_en") or "").lower()
            if ("cơm" in name or "com" in name) and ("mận" not in name):
                return 1
            if any(k in name for k in ["xôi", "xoi", "bún", "bun", "miến", "mien", "phở", "pho", "bánh mì", "banh mi"]):
                return 2
            return 3

        all_carbs.sort(key=lambda x: (carb_priority_rank(x), int(x.get("source_priority") or 1)))
        all_proteins.sort(key=lambda x: int(x.get("source_priority") or 1))
        all_fibers.sort(key=lambda x: int(x.get("source_priority") or 1))
        all_snacks.sort(key=lambda x: int(x.get("source_priority") or 1))

        # 1. Pre-generate all valid daily meal plans
        food_ids = [int(f["food_id"]) for f in domain_foods]
        if not food_ids:
            return {"feasible": False, "meal_plan": []}

        prob = Problem()

        breakfast_foods = []
        lunch_foods = []
        snack_foods = []
        dinner_foods = []

        for f in domain_foods:
            fid = int(f["food_id"])
            tags = f.get("tags") or set()
            if not tags:
                tags = get_dynamic_tags(f)
                f["tags"] = tags
            
            cat_clean = clean_category(f.get("category"))
            is_snack = "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))
            
            # If gym, heavily filter out junk foods, high-fat/sugary foods, processed/canned meats, etc.
            is_unwanted_for_gym = False
            if self.is_gym:
                if "is_dessert_snack" in tags or "is_processed" in tags or "is_condensed_milk" in tags or "is_cheese_butter" in tags or "is_dried" in tags or "is_powder" in tags:
                    if not ("is_powder" in tags and "role_protein" in tags):
                        is_unwanted_for_gym = True
                
                # Also if it's protein but not high quality, exclude it for gym
                is_p, _, _ = get_food_role(f)
                if is_p and not is_high_quality_protein(f):
                    is_unwanted_for_gym = True
                    
            if is_unwanted_for_gym:
                continue

            if "is_main_dish" in tags:
                if not is_snack:
                    breakfast_foods.append(fid)
                    lunch_foods.append(fid)
                    dinner_foods.append(fid)
            else:
                if not is_snack:
                    # Breakfast slot
                    if "allergen_egg" in tags or "role_carb" in tags or "allergen_milk" in tags or "role_fiber" in tags:
                        breakfast_foods.append(fid)
                    # Lunch/Dinner slots
                    if "role_protein" in tags or "role_carb" in tags or "role_fiber" in tags:
                        lunch_foods.append(fid)
                        dinner_foods.append(fid)
                
                # Snack slot
                if is_snack or "role_fiber" in tags or "allergen_milk" in tags or "allergen_peanut" in tags or any(k in cat_clean for k in ("trai_cay", "sua_che_pham", "hat", "khac", "rau_cu")):
                    snack_foods.append(fid)

        non_snack_food_ids = [
            int(f["food_id"]) for f in domain_foods 
            if not ("is_dessert_snack" in f.get("tags", set()) or any(k in clean_category(f.get("category")) for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot")))
        ]
        fallback_ids = non_snack_food_ids if non_snack_food_ids else food_ids

        if not breakfast_foods: breakfast_foods = fallback_ids
        if not lunch_foods: lunch_foods = fallback_ids
        if not snack_foods: snack_foods = food_ids
        if not dinner_foods: dinner_foods = fallback_ids

        exclude_snacks = self.user.get("exclude_snacks", False)

        import random
        rng = random.Random(42)
        breakfast_foods = list(breakfast_foods)
        lunch_foods = list(lunch_foods)
        dinner_foods = list(dinner_foods)
        rng.shuffle(breakfast_foods)
        rng.shuffle(lunch_foods)
        rng.shuffle(dinner_foods)

        prob.addVariable("breakfast", breakfast_foods)
        prob.addVariable("lunch", lunch_foods)
        if not exclude_snacks:
            snack_foods = list(snack_foods)
            rng.shuffle(snack_foods)
            prob.addVariable("snack", snack_foods)
        prob.addVariable("dinner", dinner_foods)

        # Apply fast daily constraints (allergy check only) during backtracking
        if not exclude_snacks:
            def check_daily_plan(b, l, s, d):
                b_food = self.food_by_id[b]
                l_food = self.food_by_id[l]
                s_food = self.food_by_id[s]
                d_food = self.food_by_id[d]
                
                if not constraints.check_allergies([b_food, l_food, s_food, d_food]):
                    return False
                return True

            prob.addConstraint(check_daily_plan, ["breakfast", "lunch", "snack", "dinner"])
        else:
            def check_daily_plan_3meals(b, l, d):
                b_food = self.food_by_id[b]
                l_food = self.food_by_id[l]
                d_food = self.food_by_id[d]
                
                if not constraints.check_allergies([b_food, l_food, d_food]):
                    return False
                return True

            prob.addConstraint(check_daily_plan_3meals, ["breakfast", "lunch", "dinner"])

        # Use iterator to avoid computing ALL solutions (extremely slow on large domains)
        solution_iter = prob.getSolutionIter()

        # 2. Score and sort baseline solutions first
        solutions_scored = []
        sol_count = 0
        MAX_SOLUTIONS_TO_SAMPLE = 500
        for sol in solution_iter:
            if sol_count >= MAX_SOLUTIONS_TO_SAMPLE:
                break
            sol_count += 1
            try:
                day_meals = self._get_meal_plan_for_solution(
                    sol, constraints, tolerance_multiplier,
                    all_carbs, all_proteins, all_fibers, all_snacks
                )
                
                if not constraints.check_daily_calories(day_meals, tolerance_multiplier):
                    continue
                if not constraints.check_daily_macros(day_meals, tolerance_multiplier):
                    continue
                
                costs = [m["cost_vnd_100g"] for m in day_meals]
                if not constraints.check_daily_budget(costs, tolerance_multiplier):
                    continue
                
                score = score_meal_plan(
                    [{"meals": day_meals}],
                    self.user.get("maximize_nutrients"),
                    self.user.get("minimize_nutrients"),
                )
                solutions_scored.append((score, sol))
            except Exception:
                continue

        if not solutions_scored:
            return {"feasible": False, "meal_plan": []}

        solutions_scored.sort(key=lambda x: x[0], reverse=True)

        # 3. Dynamic scheduling with soft recency penalties
        scheduled_plan = []
        used_food_ids: List[int] = []

        for day in range(7):
            found_day = False
            
            # Count scheduled food frequencies for global limit check
            all_scheduled_ids = []
            for day_plan in scheduled_plan:
                for meal in day_plan["meals"]:
                    all_scheduled_ids.extend(meal.get("component_food_ids", [meal["food_id"]]))
            from collections import Counter
            global_counts = Counter(all_scheduled_ids)

            # Score candidates dynamically with recency penalty
            day_candidates = []
            for base_score, sol in solutions_scored:
                try:
                    # Build temporary plan without exclusions just to get candidate food IDs
                    temp_meals = self._get_meal_plan_for_solution(
                        sol, constraints, tolerance_multiplier,
                        all_carbs, all_proteins, all_fibers, all_snacks
                    )
                    
                    cand_ids = []
                    for meal in temp_meals:
                        cand_ids.extend(meal.get("component_food_ids", [meal["food_id"]]))
                    
                    # 1. Soft constraint: calculate frequency penalty
                    freq_penalty = 0.0
                    for fid in cand_ids:
                        f = self.food_by_id[fid]
                        name = str(f.get("name_vi") or "").lower()
                        if ("cơm" in name or "com" in name) and ("mận" not in name):
                            continue
                        count = global_counts[fid]
                        if count == 1:
                            freq_penalty += 20.0
                        elif count == 2:
                            freq_penalty += 80.0
                        elif count >= 3:
                            freq_penalty += 300.0  # extremely heavy penalty
                        
                    # 2. Soft constraint: calculate recency penalty
                    recency_penalty = 0.0
                    for fid in cand_ids:
                        f = self.food_by_id[fid]
                        name = str(f.get("name_vi") or "").lower()
                        if ("cơm" in name or "com" in name) and ("mận" not in name):
                            continue
                            
                        # Yesterday (1 day ago)
                        if day >= 1:
                            prev_1_meals = scheduled_plan[-1]["meals"]
                            prev_1_ids = set()
                            for pm in prev_1_meals:
                                prev_1_ids.update(pm.get("component_food_ids", [pm["food_id"]]))
                            if fid in prev_1_ids:
                                recency_penalty += 150.0
                                
                        # 2 days ago
                        if day >= 2:
                            prev_2_meals = scheduled_plan[-2]["meals"]
                            prev_2_ids = set()
                            for pm in prev_2_meals:
                                prev_2_ids.update(pm.get("component_food_ids", [pm["food_id"]]))
                            if fid in prev_2_ids:
                                recency_penalty += 50.0
                                
                        # 3 days ago
                        if day >= 3:
                            prev_3_meals = scheduled_plan[-3]["meals"]
                            prev_3_ids = set()
                            for pm in prev_3_meals:
                                prev_3_ids.update(pm.get("component_food_ids", [pm["food_id"]]))
                            if fid in prev_3_ids:
                                recency_penalty += 20.0
                                
                    day_candidates.append((base_score - freq_penalty - recency_penalty, sol))
                except Exception:
                    continue
                    
            # Sort candidates by penalized score in descending order
            day_candidates.sort(key=lambda x: x[0], reverse=True)
            
            # Try to build and schedule the highest scoring plan
            for score, sol in day_candidates:
                try:
                    day_meals = self._get_meal_plan_for_solution(
                        sol, constraints, tolerance_multiplier,
                        all_carbs, all_proteins, all_fibers, all_snacks,
                        day_excluded_ids=set(used_food_ids)
                    )
                    
                    if not constraints.check_daily_calories(day_meals, tolerance_multiplier):
                        continue
                    if not constraints.check_daily_macros(day_meals, tolerance_multiplier):
                        continue
                    
                    costs = [m["cost_vnd_100g"] for m in day_meals]
                    if not constraints.check_daily_budget(costs, tolerance_multiplier):
                        continue
                        
                    if not constraints.check_calorie_distribution(day_meals, tolerance_multiplier):
                        continue
                        
                    cand_ids = []
                    for meal in day_meals:
                        cand_ids.extend(meal.get("component_food_ids", [meal["food_id"]]))
                        
                    scheduled_plan.append({
                        "day": day + 1,
                        "meals": day_meals,
                    })
                    used_food_ids.extend(cand_ids)
                    found_day = True
                    break
                except Exception:
                    continue
                    
            if not found_day:
                # Last-resort fallback: try to schedule highest scoring candidate without day_excluded_ids
                for score, sol in day_candidates:
                    try:
                        day_meals = self._get_meal_plan_for_solution(
                            sol, constraints, tolerance_multiplier,
                            all_carbs, all_proteins, all_fibers, all_snacks,
                            day_excluded_ids=None
                        )
                        if not constraints.check_daily_calories(day_meals, tolerance_multiplier):
                            continue
                        if not constraints.check_daily_macros(day_meals, tolerance_multiplier):
                            continue
                        costs = [m["cost_vnd_100g"] for m in day_meals]
                        if not constraints.check_daily_budget(costs, tolerance_multiplier):
                            continue
                        if not constraints.check_calorie_distribution(day_meals, tolerance_multiplier):
                            continue
                            
                        cand_ids = []
                        for meal in day_meals:
                            cand_ids.extend(meal.get("component_food_ids", [meal["food_id"]]))
                            
                        scheduled_plan.append({
                            "day": day + 1,
                            "meals": day_meals,
                        })
                        used_food_ids.extend(cand_ids)
                        found_day = True
                        break
                    except Exception:
                        continue
                        
            if not found_day:
                return {"feasible": False, "meal_plan": []}

        final_score = score_meal_plan(
            scheduled_plan,
            self.user.get("maximize_nutrients"),
            self.user.get("minimize_nutrients"),
        )

        return {
            "status": "success",
            "feasible": True,
            "meal_plan": scheduled_plan,
            "score": round(final_score, 2),
        }
