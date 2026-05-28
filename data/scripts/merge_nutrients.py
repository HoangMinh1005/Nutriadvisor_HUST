"""Merge NIN and Kaggle nutrition datasets into a single standardized CSV.

The output uses the NIN nutrient schema as the canonical reference and keeps
only the overlapping nutrient fields from both sources.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import os
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable
import unicodedata
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_NIN_PATH = ROOT_DIR / "data" / "raw" / "nin_data_raw_new.csv"
DEFAULT_KAGGLE_PATH = ROOT_DIR / "data" / "raw" / "nutrition.csv"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "raw" / "final_nutrients.csv"
DEFAULT_STRUCTURED_OUTPUT_PATH = ROOT_DIR / "data" / "raw" / "final_nutrients_structured.csv"
DEFAULT_ALIAS_OUTPUT_PATH = ROOT_DIR / "data" / "raw" / "food_aliases_vi.csv"
DEFAULT_MANIFEST_OUTPUT_PATH = ROOT_DIR / "data" / "raw" / "dataset_version_manifest.json"
DEFAULT_MANIFEST_DIR = ROOT_DIR / "data" / "raw" / "manifests"
TRANSLATION_API_URL = "https://translate.googleapis.com/translate_a/single"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

NIN_NUMERIC_COLUMNS = [
    "nang_luong_kcal",
    "chat_dam_g",
    "chat_beo_g",
    "chat_bot_duong_g",
    "vitamin_a_mcg",
    "beta_carotene_mcg",
    "vitamin_c_mg",
    "calcium_mg",
    "iron_mg",
    "zinc_mg",
    "sodium_mg",
    "cholesterol_mg",
    "magnesium_mg",
    "transfat_mg",
]

FINAL_COLUMNS = [
    "source",
    "source_id",
    "name_vi",
    "name_en",
    "category",
    *NIN_NUMERIC_COLUMNS,
]

STRUCTURED_COLUMNS = [
    *FINAL_COLUMNS,
    "canonical_name_en",
    "alias_vi",
    "source_priority",
    "match_type",
    "confidence_score",
    "canonical_key",
    "is_estimated",
]

ALIAS_COLUMNS = [
    "alias_id",
    "canonical_key",
    "canonical_name_en",
    "alias_text",
    "alias_lang",
    "alias_type",
    "is_preferred",
    "source",
    "source_priority",
]

KAGGLE_EXCLUDE_KEYWORDS = [
    "mcdonald",
    "kfc",
    "burger king",
]

USDA_TECHNICAL_REMOVE_TERMS = {
    "with added solution",
    "meat only",
    "cooked",
    "dark meat",
    "white meat",
    "raw",
    "prepared",
    "uncooked",
    "unprepared",
    "all varieties",
}

USDA_BRAND_REMOVE_TERMS = {
    "mcdonald",
    "kfc",
    "brand",
    "retail",
    "spice",
}

USDA_COOKING_METHOD_MAP = {
    "braised": "kho",
    "boiled": "luộc",
    "fried": "chiên",
    "grilled": "nướng",
    "roasted": "rang",
    "baked": "nướng",
    "steamed": "hấp",
    "smoked": "hun khói",
    "stewed": "hầm",
}

USDA_MAIN_FOOD_MAP = {
    "chicken": "gà",
    "turkey": "gà tây",
    "duck": "vịt",
    "quail": "chim cút",
    "beef": "thịt bò",
    "veal": "thịt bê",
    "lamb": "thịt cừu",
    "goat": "thịt dê",
    "pork": "thịt heo",
    "ham": "thịt heo",
    "fish": "cá",
    "salmon": "cá hồi",
    "tuna": "cá ngừ",
    "shrimp": "tôm",
    "prawn": "tôm",
    "crab": "cua",
    "squid": "mực",
    "octopus": "bạch tuộc",
    "eggplant": "cà tím",
    "broccoli": "bông cải xanh",
    "cauliflower": "súp lơ",
    "tomato": "cà chua",
    "potato": "khoai tây",
    "sweet potato": "khoai lang",
    "lettuce": "xà lách",
    "spinach": "rau bina",
    "pepper": "ớt",
    "carrot": "cà rốt",
    "onion": "hành tây",
    "mushroom": "nấm",
    "apple": "táo",
    "banana": "chuối",
    "pineapple": "dứa",
    "orange": "cam",
    "mango": "xoài",
    "egg": "trứng",
    "eggs": "trứng",
    "nuts": "hạt",
    "pecans": "hạt hồ đào",
    "almonds": "hạnh nhân",
    "peanuts": "đậu phộng",
    "rice": "gạo",
    "bread": "bánh mì",
    "noodles": "mì",
    "pasta": "mì ý",
    "corn": "bắp",
    "milk": "sữa",
    "soymilk": "sữa đậu nành",
    "soy milk": "sữa đậu nành",
    "cheese": "phô mai",
    "yogurt": "sữa chua",
    "oil": "dầu",
    "salad": "salad",
}

USDA_PART_MAP = {
    "thigh": "đùi",
    "breast": "ức",
    "wing": "cánh",
    "wings": "cánh",
    "drumstick": "đùi",
    "feet": "chân",
    "foot": "chân",
    "loin": "thăn",
    "rib": "sườn",
    "ground": "xay",
    "fillet": "phi lê",
    "giblets": "lòng",
    "skin": "vỏ",
    "boneless": "không xương",
    "crushed": "nghiền",
    "crush": "nghiền",
}

USDA_COUNTRY_MAP = {
    "french": "Pháp",
    "italian": "Ý",
    "japanese": "Nhật",
    "mexican": "Mexico",
    "american": "Mỹ",
    "chinese": "Trung Quốc",
}

USDA_FRUIT_KEYS = {
    "táo",
    "chuối",
    "dứa",
    "cam",
    "xoài",
}

USDA_DROP_ADJECTIVE_HINTS = {
    "light",
    "free fat",
    "fat free",
    "fat-free",
    "nonfat",
    "low fat",
}

USDA_CATEGORY_RULES = {
    "Gia cầm": {"chicken", "turkey", "duck", "quail"},
    "Thịt đỏ": {"beef", "veal", "lamb", "goat", "pork", "ham"},
    "Hải sản": {"fish", "salmon", "tuna", "shrimp", "prawn", "crab", "squid", "octopus"},
    "Rau củ": {"eggplant", "broccoli", "cauliflower", "tomato", "lettuce", "spinach", "pepper", "carrot", "onion", "mushroom"},
    "Tinh bột": {"rice", "bread", "noodles", "pasta", "corn", "potato", "sweet potato"},
    "Hạt": {"nuts", "pecans", "almonds", "peanuts", "walnuts", "seeds"},
    "Trái cây": {"apple", "banana", "pineapple", "orange", "mango", "grape", "strawberry", "blueberry"},
    "Sữa và chế phẩm": {"milk", "soymilk", "soy milk", "cheese", "yogurt", "kefir", "butter"},
    "Trứng": {"egg", "eggs"},
}

USDA_GENERIC_ONLY_HINTS = {
    "vitamin",
    "fortified",
    "added",
    "calcium",
    "light",
    "chocolate",
    "vanilla",
    "flavor",
    "flavored",
}

KAGGLE_PROTECTED_TERMS = {
    "raw": "sống",
    "fresh": "tươi",
    "cooked": "chín",
    "boiled": "luộc",
    "fried": "chiên",
    "baked": "nướng",
    "roasted": "rang",
    "broiled": "nướng",
    "grilled": "nướng",
    "steamed": "hấp",
    "smoked": "hun khói",
    "canned": "đóng hộp",
    "frozen": "đông lạnh",
    "dried": "sấy khô",
    "dry": "khô",
    "drained": "đã để ráo",
    "with salt": "có muối",
    "without salt": "không muối",
    "uncooked": "chưa nấu",
    "unprepared": "chưa chế biến",
    "boneless": "không xương",
    "bone-in": "có xương",
    "skinless": "không da",
    "with skin": "có da",
    "cured": "ướp muối",
    "uncured": "không ướp muối",
    "lean": "nạc",
    "fat": "mỡ",
    "meat only": "chỉ thịt",
    "lean only": "chỉ nạc",
    "lean and fat": "nạc và mỡ",
    "separable lean and fat": "nạc và mỡ tách riêng",
    "separable lean only": "chỉ nạc tách riêng",
    "pastrami": "pastrami",
    "chinese": "kiểu Trung Quốc",
    "italian": "kiểu Ý",
    "japanese": "kiểu Nhật",
    "mexican": "kiểu Mexico",
    "american": "kiểu Mỹ",
}

KAGGLE_POST_REPLACEMENTS = [
    (r"\bchữa khỏi\b", "ướp muối"),
    (r"\bnguyên liệu\b", "sống"),
    (r"\btiếng Trung Quốc\b", "kiểu Trung Quốc"),
]

KAGGLE_PHRASE_TRANSLATIONS = [
    ("bacon and beef sticks", "que thịt xông khói và thịt bò"),
    ("chicken feet", "chân gà"),
    ("broccoli raab", "cải bẹ xanh"),
    ("egg custards", "bánh trứng"),
    ("egg custard", "bánh trứng"),
    ("dry mix", "hỗn hợp khô"),
    ("fruit butters", "bơ trái cây"),
    ("potato sticks", "que khoai tây"),
    ("rice noodles", "bún gạo"),
    ("salad taco", "salad taco"),
    ("taco salad", "salad taco"),
    ("soy yogurt", "sữa chua đậu nành"),
    ("soymilk", "sữa đậu nành"),
    ("with skin", "có da"),
    ("without salt", "không muối"),
    ("with salt", "có muối"),
    ("lean and fat", "nạc và mỡ"),
    ("separable lean and fat", "nạc và mỡ tách riêng"),
    ("separable lean only", "chỉ nạc tách riêng"),
    ("meat only", "chỉ thịt"),
    ("lean only", "chỉ nạc"),
]

KAGGLE_WORD_TRANSLATIONS = {
    "apple": "táo",
    "apples": "táo",
    "baked": "nướng",
    "banana": "chuối",
    "bananas": "chuối",
    "beef": "thịt bò",
    "berries": "quả mọng",
    "berry": "quả mọng",
    "bread": "bánh mì",
    "broccoli": "bông cải xanh",
    "butter": "bơ",
    "canned": "đóng hộp",
    "carrot": "cà rốt",
    "carrots": "cà rốt",
    "cauliflower": "súp lơ",
    "chicken": "gà",
    "chocolate": "sô cô la",
    "cooked": "chín",
    "cured": "ướp muối",
    "dried": "sấy khô",
    "dry": "khô",
    "duck": "vịt",
    "egg": "trứng",
    "eggplant": "cà tím",
    "eggs": "trứng",
    "egg custard": "bánh trứng",
    "egg custards": "bánh trứng",
    "fish": "cá",
    "fresh": "tươi",
    "frozen": "đông lạnh",
    "fried": "chiên",
    "grilled": "nướng",
    "haddock": "tuyết chấm đen",
    "ham": "giăm bông",
    "herring": "cá trích",
    "kelp": "rong biển",
    "kefir": "kefir",
    "lamb": "thịt cừu",
    "lettuce": "xà lách",
    "mackerel": "cá thu",
    "milk": "sữa",
    "mushroom": "nấm",
    "mushrooms": "nấm",
    "noodles": "mì",
    "orange": "cam",
    "oranges": "cam",
    "pastrami": "pastrami",
    "peach": "đào",
    "peaches": "đào",
    "pear": "lê",
    "peas": "đậu Hà Lan",
    "pork": "thịt heo",
    "potato": "khoai tây",
    "potatoes": "khoai tây",
    "raw": "sống",
    "rice": "cơm",
    "roasted": "rang",
    "salad": "salad",
    "salami": "xúc xích salami",
    "salmon": "cá hồi",
    "sausage": "xúc xích",
    "sesame": "vừng",
    "sheepshead": "cá đầu cừu",
    "skinless": "không da",
    "smoked": "hun khói",
    "soy": "đậu nành",
    "steamed": "hấp",
    "strawberry": "dâu tây",
    "strawberries": "dâu tây",
    "sugar": "đường",
    "syrup": "xi-rô",
    "taco": "taco",
    "tomato": "cà chua",
    "tomatoes": "cà chua",
    "turkey": "gà tây",
    "vanilla": "vani",
    "water": "nước",
    "yogurt": "sữa chua",
    "zucchini": "bí ngòi",
    "pineapple": "dứa",
    "pineapples": "dứa",
    "gala": "gala",
    "fuji": "fuji",
    "granny smith": "granny smith",
    "pink lady": "pink lady",
    "honeycrisp": "honeycrisp",
    "golden delicious": "golden delicious",
    "red delicious": "red delicious",
    "braeburn": "braeburn",
    "wolffish": "cá sói",
    "ling": "cá linh",
    "cusk": "cá cusk",
    "atlantic": "đại tây dương",
    "pacific": "thái bình dương",
    "coho": "coho",
    "sockeye": "sockeye",
    "chinook": "chinook",
    "bollilo": "bánh mì cuộn",
    "beerwurst": "xúc xích bia",
    "beer salami": "xúc xích bia",
    "olive": "ôliu",
    "olives": "ôliu",
    "oil": "dầu",
    "babyfood": "thức ăn trẻ em",
    "junior": "cấp độ 2",
}

KAGGLE_DESCRIPTOR_TRANSLATIONS = {
    "raw": "sống",
    "fresh": "tươi",
    "cooked": "chín",
    "boiled": "luộc",
    "fried": "chiên",
    "baked": "nướng",
    "roasted": "rang",
    "broiled": "nướng",
    "grilled": "nướng",
    "steamed": "hấp",
    "smoked": "hun khói",
    "canned": "đóng hộp",
    "frozen": "đông lạnh",
    "dried": "sấy khô",
    "dry": "khô",
    "drained": "đã để ráo",
    "with salt": "có muối",
    "without salt": "không muối",
    "uncooked": "chưa nấu",
    "unprepared": "chưa chế biến",
    "boneless": "không xương",
    "bone-in": "có xương",
    "skinless": "không da",
    "with skin": "có da",
    "cured": "ướp muối",
    "uncured": "không ướp muối",
    "lean": "nạc",
    "fat": "mỡ",
    "meat only": "chỉ thịt",
    "lean only": "chỉ nạc",
    "lean and fat": "nạc và mỡ",
    "separable lean and fat": "nạc và mỡ tách riêng",
    "separable lean only": "chỉ nạc tách riêng",
    "chinese": "kiểu Trung Quốc",
    "italian": "kiểu Ý",
    "japanese": "kiểu Nhật",
    "mexican": "kiểu Mexico",
    "american": "kiểu Mỹ",
}

KAGGLE_BASE_TRANSLATIONS = {
    "apple": "táo",
    "apples": "táo",
    "banana": "chuối",
    "bananas": "chuối",
    "beef": "thịt bò",
    "bread": "bánh mì",
    "broccoli": "bông cải xanh",
    "broccoli raab": "cải bẹ xanh",
    "butter": "bơ",
    "carrot": "cà rốt",
    "carrots": "cà rốt",
    "cauliflower": "súp lơ",
    "chicken": "gà",
    "chocolate": "sô cô la",
    "duck": "vịt",
    "egg": "trứng",
    "eggplant": "cà tím",
    "eggs": "trứng",
    "fish": "cá",
    "fruit butters": "bơ trái cây",
    "ham": "giăm bông",
    "haddock": "tuyết chấm đen",
    "herring": "cá trích",
    "lamb": "thịt cừu",
    "lettuce": "xà lách",
    "mackerel": "cá thu",
    "milk": "sữa",
    "mushroom": "nấm",
    "mushrooms": "nấm",
    "noodles": "mì",
    "orange": "cam",
    "oranges": "cam",
    "pastrami": "pastrami",
    "peach": "đào",
    "peaches": "đào",
    "pear": "lê",
    "peas": "đậu Hà Lan",
    "pork": "thịt heo",
    "potato": "khoai tây",
    "potatoes": "khoai tây",
    "rice": "cơm",
    "salad": "salad",
    "salami": "xúc xích salami",
    "salmon": "cá hồi",
    "sausage": "xúc xích",
    "sesame": "vừng",
    "sheepshead": "đầu cừu",
    "snacks": "món ăn vặt",
    "soy": "đậu nành",
    "soy yogurt": "sữa chua đậu nành",
    "soymilk": "sữa đậu nành",
    "sugar": "đường",
    "taco": "taco",
    "taco salad": "salad taco",
    "tomato": "cà chua",
    "tomatoes": "cà chua",
    "turkey": "gà tây",
    "vanilla": "vani",
    "water": "nước",
    "yogurt": "sữa chua",
    "zucchini": "bí ngòi",
    "pineapple": "dứa",
    "pineapples": "dứa",
    "gala": "gala",
    "fuji": "fuji",
    "granny smith": "granny smith",
    "pink lady": "pink lady",
    "honeycrisp": "honeycrisp",
    "golden delicious": "golden delicious",
    "red delicious": "red delicious",
    "braeburn": "braeburn",
    "wolffish": "cá sói",
    "ling": "cá linh",
    "cusk": "cá cusk",
    "atlantic": "đại tây dương",
    "pacific": "thái bình dương",
    "coho": "coho",
    "sockeye": "sockeye",
    "chinook": "chinook",
    "bollilo": "bánh mì cuộn",
    "beerwurst": "xúc xích bia",
    "beer salami": "xúc xích bia",
    "olive": "ôliu",
    "olives": "ôliu",
    "oil": "dầu",
    "babyfood": "thức ăn trẻ em",
    "junior": "cấp độ 2",
}

TRANSLATION_PROVIDER = os.getenv("KAGGLE_TRANSLATION_PROVIDER", "gemini").strip().lower()

KAGGLE_PART_TERMS = {
    "feet": "chân gà",
    "foot": "chân gà",
    "yolk": "lòng đỏ",
    "leaves": "lá",
    "stalks": "thân",
    "breast": "ức",
    "wing": "cánh",
    "wings": "cánh",
    "thigh": "đùi",
    "drumstick": "đùi",
    "fillet": "phi lê",
    "meat": "thịt",
    "skin": "da",
    "sheepshead": "đầu cừu",
    "butterfish": "bơ",
    "mahimahi": "mahi mahi",
    "sablefish": "sablefish",
    "swordfish": "kiếm",
    "milkfish": "măng",
    "monkfish": "chày",
}

KAGGLE_CATEGORY_ORDER = {
    "part": 0,
    "prep": 1,
    "style": 2,
    "other": 3,
}


def _clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "null", "none", "tr", "-"}:
        return ""
    return text


def _parse_numeric(value: object) -> float:
    """Parse a numeric value from raw CSV text.

    Handles values like "15g", "9.00 mg", "0,2", "tr", "-", and blanks.
    """
    text = _clean_text(value)
    if not text:
        return 0.0

    lowered = text.lower()
    if lowered in {"tr", "-", "nan", "null", "none"}:
        return 0.0

    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    if not match:
        return 0.0

    number_text = match.group(0).replace(",", ".")
    try:
        return float(number_text)
    except ValueError:
        return 0.0


def _normalize_name(value: object) -> str:
    return " ".join(_clean_text(value).lower().split())


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    without_marks = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return without_marks.replace("đ", "d").replace("Đ", "D")


def _pick_source_id_column(frame: pd.DataFrame) -> str:
    if "Unnamed: 0" in frame.columns:
        return "Unnamed: 0"
    return frame.columns[0]


def _infer_kaggle_category(name: str) -> str:
    lower_name = _clean_text(name).lower()
    for category, keywords in USDA_CATEGORY_RULES.items():
        if any(keyword in lower_name for keyword in keywords):
            return category
    return "Khác"


def _remove_usda_noise(name: str) -> str:
    cleaned = _clean_text(name).lower()
    cleaned = cleaned.replace('"', " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    for term in sorted(USDA_TECHNICAL_REMOVE_TERMS | USDA_BRAND_REMOVE_TERMS, key=len, reverse=True):
        cleaned = re.sub(rf"(?<!\w){re.escape(term)}(?!\w)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned


def _pick_cooking_method(cleaned_name: str) -> str:
    for english, vietnamese in USDA_COOKING_METHOD_MAP.items():
        if re.search(rf"(?<!\w){re.escape(english)}(?!\w)", cleaned_name):
            return vietnamese
    return ""


def _pick_main_food(cleaned_name: str) -> str:
    for english, vietnamese in USDA_MAIN_FOOD_MAP.items():
        if re.search(rf"(?<!\w){re.escape(english)}(?!\w)", cleaned_name):
            return vietnamese
    return ""


def _pick_part(cleaned_name: str) -> str:
    for english, vietnamese in USDA_PART_MAP.items():
        if re.search(rf"(?<!\w){re.escape(english)}(?!\w)", cleaned_name):
            return vietnamese
    return ""


def _pick_country(cleaned_name: str) -> str:
    for english, vietnamese in USDA_COUNTRY_MAP.items():
        if re.search(rf"(?<!\w){re.escape(english)}(?!\w)", cleaned_name):
            return vietnamese
    return ""


def _has_raw_or_fresh(original_name: str) -> bool:
    lowered = _clean_text(original_name).lower()
    return "raw" in lowered or "fresh" in lowered


def _cleanup_vi_food_name(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""

    cleaned = re.sub(r"\bnghiền nát\b", "nghiền", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bnhẹ nhàng\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bánh sáng\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned


def _finalize_vi_text(text: str) -> str:
    text = re.sub(r"\s+", " ", _clean_text(text)).strip(" ,.-")
    if not text:
        return ""
    return text[0].upper() + text[1:]


def _normalize_usda_name_vi(name_en: object) -> str:
    original = _clean_text(name_en)
    if not original:
        return ""

    cleaned_name = _remove_usda_noise(original)
    method_vi = _pick_cooking_method(cleaned_name)
    main_vi = _pick_main_food(cleaned_name)
    part_vi = _pick_part(cleaned_name)
    country_vi = _pick_country(cleaned_name)
    has_raw_or_fresh = _has_raw_or_fresh(original)

    # Prefer deterministic USDA normalization before fallback translation.
    if main_vi:
        if main_vi == "salad":
            if country_vi:
                return f"Salad {country_vi}"
            return "Salad"

        if any(hint in cleaned_name for hint in USDA_GENERIC_ONLY_HINTS):
            if main_vi == "sữa đậu nành":
                return "Sữa đậu nành"
            if main_vi == "salad" and country_vi:
                return f"Salad {country_vi}"
            return _finalize_vi_text(main_vi)

        if any(hint in cleaned_name for hint in USDA_DROP_ADJECTIVE_HINTS):
            if main_vi == "salad" and country_vi:
                return f"Salad {country_vi}"
            return _finalize_vi_text(main_vi)

        base = main_vi
        if "whole" in _clean_text(original).lower() and (main_vi in USDA_FRUIT_KEYS or main_vi == "trứng"):
            base = f"{main_vi} cả quả"
        elif part_vi and part_vi not in main_vi:
            base = f"{part_vi} {main_vi}"

        if method_vi:
            normalized = _finalize_vi_text(f"{base} {method_vi}")
        else:
            normalized = _finalize_vi_text(base)

        if has_raw_or_fresh and main_vi in USDA_FRUIT_KEYS:
            normalized = _finalize_vi_text(f"{main_vi} tươi")

        return _cleanup_vi_food_name(normalized)

    fallback = _translate_kaggle_name(original)
    fallback = _remove_consecutive_duplicates(_normalize_vietnamese_name(fallback))
    return _cleanup_vi_food_name(_finalize_vi_text(fallback))


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize_vietnamese_name(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""

    cleaned = cleaned.replace("/", " ")
    cleaned = cleaned.replace("(", " ").replace(")", " ")
    cleaned = cleaned.replace(";", ",")
    cleaned = re.sub(r"\s*,\s*", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def _remove_consecutive_duplicates(text: str) -> str:
    """Remove duplicate words from Vietnamese text (both consecutive and non-consecutive).
    
    Keeps the first occurrence of each word and removes later duplicates.
    """
    words = text.split()
    if not words:
        return text
    
    seen = set()
    result = []
    for word in words:
        word_lower = word.lower()
        if word_lower not in seen:
            result.append(word)
            seen.add(word_lower)
    
    return " ".join(result)


def _protect_kaggle_terms(text: str) -> tuple[str, dict[str, str]]:
    protected_text = _clean_text(text)
    restore_map: dict[str, str] = {}

    terms = sorted(KAGGLE_PROTECTED_TERMS.items(), key=lambda item: len(item[0]), reverse=True)
    for index, (term, vietnamese) in enumerate(terms):
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", flags=re.IGNORECASE)
        placeholder = f"__KAGGLE_TERM_{index}__"
        protected_text, count = pattern.subn(placeholder, protected_text)
        if count:
            restore_map[placeholder] = vietnamese

    return protected_text, restore_map


def _restore_kaggle_terms(text: str, restore_map: dict[str, str]) -> str:
    restored = text
    for placeholder, vietnamese in restore_map.items():
        restored = restored.replace(placeholder, vietnamese)
    return restored


def _apply_post_replacements(text: str) -> str:
    result = text
    for pattern, replacement in KAGGLE_POST_REPLACEMENTS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _extract_translation_candidate(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""

    cleaned = cleaned.replace("/", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.strip(".:-")
    return cleaned


def _apply_local_kaggle_translations(text: str) -> str:
    result = _clean_text(text).lower()
    if not result:
        return ""

    result = result.replace(",", " ")
    result = result.replace("/", " ")
    result = re.sub(r"\s+", " ", result).strip()

    for phrase, vietnamese in sorted(KAGGLE_PHRASE_TRANSLATIONS, key=lambda item: len(item[0]), reverse=True):
        result = re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", vietnamese, result, flags=re.IGNORECASE)

    for english, vietnamese in KAGGLE_WORD_TRANSLATIONS.items():
        result = re.sub(rf"(?<!\w){re.escape(english)}(?!\w)", vietnamese, result, flags=re.IGNORECASE)

    result = _apply_post_replacements(result)
    result = re.sub(r"\s+", " ", result).strip()
    return result


def _translate_segment(segment: str) -> str:
    normalized = _clean_text(segment).lower().strip()
    if not normalized:
        return ""

    if normalized in KAGGLE_BASE_TRANSLATIONS:
        return KAGGLE_BASE_TRANSLATIONS[normalized]

    for phrase, vietnamese in sorted(KAGGLE_BASE_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True):
        if phrase in normalized:
            return vietnamese

    local_translated = _apply_local_kaggle_translations(normalized)
    if local_translated and not _has_untranslated_english_words(local_translated):
        return local_translated

    protected_text, restore_map = _protect_kaggle_terms(normalized)
    translated = _translate_with_api(protected_text)
    if not translated:
        translated = _normalize_vietnamese_name(normalized)

    translated = _restore_kaggle_terms(translated, restore_map)
    translated = _apply_post_replacements(translated)
    return _normalize_vietnamese_name(translated)


def _categorize_segment(segment: str) -> tuple[int, str]:
    normalized = _clean_text(segment).lower().strip()
    if not normalized:
        return KAGGLE_CATEGORY_ORDER["other"], ""

    if normalized in KAGGLE_PART_TERMS:
        return KAGGLE_CATEGORY_ORDER["part"], KAGGLE_PART_TERMS[normalized]

    if normalized in {"raw", "fresh", "cooked", "boiled", "fried", "baked", "roasted", "broiled", "grilled", "steamed", "smoked", "canned", "frozen", "dried", "dry", "drained", "uncooked", "unprepared", "with salt", "without salt", "cured", "uncured", "lean", "fat", "meat only", "lean only", "lean and fat", "separable lean and fat", "separable lean only", "boneless", "bone-in", "skinless", "with skin"}:
        return KAGGLE_CATEGORY_ORDER["prep"], _translate_segment(normalized)

    if normalized in {"chinese", "italian", "japanese", "mexican", "american"}:
        return KAGGLE_CATEGORY_ORDER["style"], _translate_segment(normalized)

    return KAGGLE_CATEGORY_ORDER["other"], _translate_segment(normalized)


def _assemble_comma_name(parts: list[str]) -> str:
    if not parts:
        return ""

    base = _translate_segment(parts[0])
    modifiers = []
    for part in parts[1:]:
        if not _clean_text(part):
            continue
        order, translated = _categorize_segment(part)
        if translated:
            modifiers.append((order, translated))

    translated_modifiers = [part.lower() for _, part in sorted(modifiers, key=lambda item: item[0])]

    if not translated_modifiers:
        result = _normalize_vietnamese_name(base)
    else:
        result = _normalize_vietnamese_name(" ".join([base, *translated_modifiers]))
    
    return _remove_consecutive_duplicates(result)


def _has_untranslated_english_words(text: str) -> bool:
    return bool(re.search(r"\b[a-z]{3,}\b", _clean_text(text).lower()))


def _looks_like_brand_prefix(text: str) -> bool:
    cleaned = _clean_text(text)
    if not cleaned:
        return False

    tokens = cleaned.split()
    if not tokens:
        return False

    if any(token.isupper() and len(token) > 1 for token in tokens):
        return True

    if len(tokens) <= 3 and cleaned.upper() == cleaned:
        return True

    return False


@lru_cache(maxsize=8192)
def _translate_with_google(text: str) -> str:
    query = urlencode({"client": "gtx", "sl": "en", "tl": "vi", "dt": "t", "q": text})
    url = f"{TRANSLATION_API_URL}?{query}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
            translated = "".join(part[0] for part in payload[0] if part and part[0])
            cleaned = _normalize_vietnamese_name(translated)
            if cleaned:
                return cleaned
        except (URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 2:
                break

    return ""


def _translate_with_gemini(text: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return ""

    prompt = (
        "You are a food name translator from English to Vietnamese. Translate this food name naturally and accurately.\n"
        "Rules: (1) Only return the translation, nothing else. (2) Do not repeat words. (3) If the name contains "
        "varieties/species, translate them accurately (e.g., 'Pineapple' -> 'Dứa', not 'Táo'). "
        "(4) Arrange modifiers in natural Vietnamese order: base + part/type + cooking method + style.\n"
        f"Translate: {text}"
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 64,
        },
    }
    request = Request(
        f"{GEMINI_API_URL}?key={api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        candidates = payload.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        translated = " ".join(part.get("text", "") for part in parts).strip()
        result = _normalize_vietnamese_name(_extract_translation_candidate(translated))
        return _remove_consecutive_duplicates(result)
    except (URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        return ""


def _translate_with_openai(text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ""

    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [
            {
                "role": "system",
                "content": "Ban la cong cu dich ten mon an tu tieng Anh sang tieng Viet. Chi tra ve ban dich ngan gon, tu nhien, khong giai thich.",
            },
            {
                "role": "user",
                "content": f"Dich ten mon an nay: {text}",
            },
        ],
        "temperature": 0.1,
        "max_tokens": 64,
    }
    request = Request(
        OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        choices = payload.get("choices", [])
        if not choices:
            return ""
        translated = choices[0].get("message", {}).get("content", "")
        result = _normalize_vietnamese_name(_extract_translation_candidate(translated))
        return _remove_consecutive_duplicates(result)
    except (URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError):
        return ""


def _translate_with_api(text: str) -> str:
    preferred = _extract_translation_candidate(text)
    if not preferred:
        return ""

    providers = []
    if TRANSLATION_PROVIDER == "openai":
        providers = [_translate_with_openai, _translate_with_gemini, _translate_with_google]
    elif TRANSLATION_PROVIDER == "google":
        providers = [_translate_with_google, _translate_with_gemini, _translate_with_openai]
    else:
        providers = [_translate_with_gemini, _translate_with_openai, _translate_with_google]

    for provider in providers:
        translated = provider(preferred)
        if translated:
            return translated

    return ""


def _translate_kaggle_name(name_en: object) -> str:
    text = _clean_text(name_en)
    if not text:
        return ""

    lowered = text.lower()
    if "chicken" in lowered and "feet" in lowered:
        if "boiled" in lowered or "cooked" in lowered:
            return "Chân gà luộc"
        if "fried" in lowered:
            return "Chân gà chiên"
        return "Chân gà"

    comma_parts = [part.strip() for part in text.split(",") if _clean_text(part)]
    if len(comma_parts) > 1:
        prefix = comma_parts[0]
        if _looks_like_brand_prefix(prefix):
            suffix_translation = _assemble_comma_name(comma_parts[1:])
            if suffix_translation:
                result = _normalize_vietnamese_name(f"{suffix_translation} - {prefix}")
                return _remove_consecutive_duplicates(result)
        structured_translation = _assemble_comma_name(comma_parts)
        if structured_translation:
            return _remove_consecutive_duplicates(structured_translation)

    result = _translate_segment(text)
    return _remove_consecutive_duplicates(result)


def _load_nin_dataset(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str)

    renamed = frame.rename(
        columns={
            "ten_mon_an": "name_vi",
            "ten_mon_an_en": "name_en",
            "nhom": "category",
            "ma_so": "source_id",
        }
    )

    output = pd.DataFrame(index=renamed.index.copy())
    output["source"] = "NIN"
    output["source_id"] = renamed.get("source_id", "").map(_clean_text)
    output["name_vi"] = renamed.get("name_vi", "").map(_clean_text)
    output["name_en"] = renamed.get("name_en", "").map(_clean_text)
    output["category"] = renamed.get("category", "").map(_clean_text)

    for column in NIN_NUMERIC_COLUMNS:
        output[column] = renamed.get(column, 0).map(_parse_numeric)

    return output


def _load_kaggle_dataset(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str)
    source_id_column = _pick_source_id_column(frame)

    working = frame.copy()
    if source_id_column == "Unnamed: 0":
        working = working.drop(columns=[source_id_column])

    name_series = working["name"].fillna("").astype(str)
    lower_name = name_series.str.lower().str.strip()
    exclude_mask = lower_name.apply(lambda value: _contains_any(value, KAGGLE_EXCLUDE_KEYWORDS))
    working = working.loc[~exclude_mask].copy()

    output = pd.DataFrame(index=working.index.copy())
    output["source"] = "Kaggle"
    output["source_id"] = frame.loc[working.index, source_id_column].astype(str).map(_clean_text)
    output["name_vi"] = ""
    output["name_en"] = working["name"].map(_clean_text)
    output["category"] = working["name"].map(_infer_kaggle_category)

    output["nang_luong_kcal"] = working.get("calories", 0).map(_parse_numeric)
    output["chat_dam_g"] = working.get("protein", 0).map(_parse_numeric)
    output["chat_beo_g"] = working.get("total_fat", working.get("fat", 0)).map(_parse_numeric)
    output["chat_bot_duong_g"] = working.get("carbohydrate", 0).map(_parse_numeric)
    output["vitamin_a_mcg"] = working.get("vitamin_a_rae", working.get("vitamin_a", 0)).map(_parse_numeric)
    output["beta_carotene_mcg"] = working.get("carotene_beta", 0).map(_parse_numeric)
    output["vitamin_c_mg"] = working.get("vitamin_c", 0).map(_parse_numeric)
    output["calcium_mg"] = working.get("calcium", 0).map(_parse_numeric)
    output["iron_mg"] = working.get("irom", working.get("iron", 0)).map(_parse_numeric)
    output["zinc_mg"] = working.get("zink", working.get("zinc", 0)).map(_parse_numeric)
    output["sodium_mg"] = working.get("sodium", 0).map(_parse_numeric)
    output["cholesterol_mg"] = working.get("cholesterol", 0).map(_parse_numeric)
    output["magnesium_mg"] = working.get("magnesium", 0).map(_parse_numeric)
    output["transfat_mg"] = working.get("fatty_acids_total_trans", 0).map(_parse_numeric)

    return output


def _merge_with_nin_priority(nin_frame: pd.DataFrame, kaggle_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    nin_name_set = {
        normalized_name
        for normalized_name in nin_frame["name_en"].map(_normalize_name)
        if normalized_name
    }

    kaggle_filtered = kaggle_frame.loc[
        ~kaggle_frame["name_en"].map(_normalize_name).isin(nin_name_set)
    ].copy()

    # Keep all NIN rows as canonical data; deduplicate only inside Kaggle by EN key.
    kaggle_filtered["_name_en_norm"] = kaggle_filtered["name_en"].map(_normalize_name)
    kaggle_filtered = kaggle_filtered.loc[kaggle_filtered["_name_en_norm"] != ""].copy()
    kaggle_filtered = kaggle_filtered.loc[
        ~kaggle_filtered["_name_en_norm"].duplicated(keep="first")
    ].copy()

    return nin_frame.copy(), kaggle_filtered


def build_final_dataset(nin_path: Path, kaggle_path: Path) -> pd.DataFrame:
    nin_frame = _load_nin_dataset(nin_path)
    kaggle_frame = _load_kaggle_dataset(kaggle_path)
    nin_frame, kaggle_frame = _merge_with_nin_priority(nin_frame, kaggle_frame)
    kaggle_frame = kaggle_frame.drop(columns=["_name_en_norm"])

    combined = pd.concat([nin_frame, kaggle_frame], ignore_index=True)

    for column in NIN_NUMERIC_COLUMNS:
        combined[column] = combined[column].apply(_parse_numeric).astype(float)

    for column in ["source", "source_id", "name_vi", "name_en", "category"]:
        combined[column] = combined[column].map(_clean_text)

    combined = combined[FINAL_COLUMNS]
    combined = combined.fillna(0.0)
    combined[NIN_NUMERIC_COLUMNS] = combined[NIN_NUMERIC_COLUMNS].fillna(0.0).astype(float)
    return combined


def build_structured_dataset(nin_path: Path, kaggle_path: Path) -> pd.DataFrame:
    nin_frame = _load_nin_dataset(nin_path)
    kaggle_frame = _load_kaggle_dataset(kaggle_path)
    nin_frame, kaggle_frame = _merge_with_nin_priority(nin_frame, kaggle_frame)

    nin_structured = nin_frame.copy()
    nin_structured["canonical_name_en"] = nin_structured["name_en"]
    nin_structured["alias_vi"] = nin_structured["name_vi"]
    nin_structured["source_priority"] = 1
    nin_structured["match_type"] = "canonical_nin"
    nin_structured["confidence_score"] = 1.0
    nin_structured["canonical_key"] = nin_structured["canonical_name_en"].map(_normalize_name)
    nin_structured["is_estimated"] = False

    kaggle_structured = kaggle_frame.copy()
    kaggle_structured["canonical_name_en"] = kaggle_structured["name_en"]
    kaggle_structured["alias_vi"] = ""
    kaggle_structured["source_priority"] = 2
    kaggle_structured["match_type"] = "kaggle_new_only"
    kaggle_structured["confidence_score"] = 0.65
    kaggle_structured["canonical_key"] = kaggle_structured["_name_en_norm"]
    kaggle_structured["is_estimated"] = False
    kaggle_structured = kaggle_structured.drop(columns=["_name_en_norm"])

    structured = pd.concat([nin_structured, kaggle_structured], ignore_index=True)
    for column in NIN_NUMERIC_COLUMNS:
        structured[column] = structured[column].apply(_parse_numeric).astype(float)

    for column in [
        "source",
        "source_id",
        "name_vi",
        "name_en",
        "canonical_name_en",
        "alias_vi",
        "category",
        "match_type",
        "canonical_key",
    ]:
        structured[column] = structured[column].map(_clean_text)

    structured = structured[STRUCTURED_COLUMNS]
    structured = structured.fillna(0.0)
    structured[NIN_NUMERIC_COLUMNS] = structured[NIN_NUMERIC_COLUMNS].fillna(0.0).astype(float)
    return structured


def build_alias_dataset(structured_frame: pd.DataFrame) -> pd.DataFrame:
    vi_base = structured_frame.loc[
        (structured_frame["source"] == "NIN") & (structured_frame["alias_vi"].map(_clean_text) != "")
    ].copy()

    if vi_base.empty:
        return pd.DataFrame(columns=ALIAS_COLUMNS)

    vi_base["alias_preferred"] = vi_base["alias_vi"].map(_clean_text)
    vi_base["alias_no_diacritic"] = vi_base["alias_preferred"].map(_strip_accents).map(_normalize_name)

    preferred_aliases = pd.DataFrame(
        {
            "canonical_key": vi_base["canonical_key"],
            "canonical_name_en": vi_base["canonical_name_en"],
            "alias_text": vi_base["alias_preferred"],
            "alias_lang": "vi",
            "alias_type": "display",
            "is_preferred": True,
            "source": vi_base["source"],
            "source_priority": vi_base["source_priority"],
        }
    )

    nodiacritic_aliases = pd.DataFrame(
        {
            "canonical_key": vi_base["canonical_key"],
            "canonical_name_en": vi_base["canonical_name_en"],
            "alias_text": vi_base["alias_no_diacritic"],
            "alias_lang": "vi",
            "alias_type": "non_diacritic",
            "is_preferred": False,
            "source": vi_base["source"],
            "source_priority": vi_base["source_priority"],
        }
    )

    alias_frame = pd.concat([preferred_aliases, nodiacritic_aliases], ignore_index=True)
    alias_frame["alias_text"] = alias_frame["alias_text"].map(_clean_text)
    alias_frame = alias_frame.loc[alias_frame["alias_text"] != ""].copy()
    alias_frame = alias_frame.drop_duplicates(subset=["canonical_key", "alias_text"], keep="first")
    alias_frame = alias_frame.reset_index(drop=True)
    alias_frame["alias_id"] = alias_frame.index.map(lambda index: f"ALIAS-{index + 1:06d}")
    alias_frame = alias_frame[ALIAS_COLUMNS]
    return alias_frame


def _file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def build_version_manifest(
    version_tag: str,
    nin_path: Path,
    kaggle_path: Path,
    final_path: Path,
    structured_path: Path,
    alias_path: Path,
    structured_frame: pd.DataFrame,
) -> dict[str, object]:
    source_counts = structured_frame["source"].value_counts().to_dict()
    return {
        "version_tag": version_tag,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "nin": str(nin_path),
            "kaggle": str(kaggle_path),
        },
        "row_counts": {
            "total": int(len(structured_frame)),
            "by_source": {key: int(value) for key, value in source_counts.items()},
        },
        "outputs": {
            "final_nutrients_csv": {
                "path": str(final_path),
                "md5": _file_md5(final_path),
            },
            "final_nutrients_structured_csv": {
                "path": str(structured_path),
                "md5": _file_md5(structured_path),
            },
            "food_aliases_vi_csv": {
                "path": str(alias_path),
                "md5": _file_md5(alias_path),
            },
        },
        "notes": "NIN is canonical; Kaggle is supplement-only. EN-first canonical key with VI alias layer.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge NIN and Kaggle nutrients into one CSV")
    parser.add_argument("--nin", default=str(DEFAULT_NIN_PATH), help="Path to nin_data_raw_new.csv")
    parser.add_argument("--kaggle", default=str(DEFAULT_KAGGLE_PATH), help="Path to nutrition.csv")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Path to final_nutrients.csv")
    parser.add_argument(
        "--structured-output",
        default=str(DEFAULT_STRUCTURED_OUTPUT_PATH),
        help="Path to final_nutrients_structured.csv",
    )
    parser.add_argument(
        "--alias-output",
        default=str(DEFAULT_ALIAS_OUTPUT_PATH),
        help="Path to food_aliases_vi.csv",
    )
    parser.add_argument(
        "--manifest-output",
        default=str(DEFAULT_MANIFEST_OUTPUT_PATH),
        help="Path to dataset_version_manifest.json",
    )
    parser.add_argument(
        "--manifest-dir",
        default=str(DEFAULT_MANIFEST_DIR),
        help="Directory for versioned manifests (e.g., dataset_v1.1.0.json)",
    )
    parser.add_argument(
        "--version-tag",
        default="v1.0.0",
        help="Dataset version tag for manifest",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    nin_path = Path(args.nin)
    kaggle_path = Path(args.kaggle)
    output_path = Path(args.output)
    structured_output_path = Path(args.structured_output)
    alias_output_path = Path(args.alias_output)
    manifest_output_path = Path(args.manifest_output)
    manifest_dir = Path(args.manifest_dir)

    if not nin_path.exists():
        raise FileNotFoundError(f"NIN file not found: {nin_path}")
    if not kaggle_path.exists():
        raise FileNotFoundError(f"Kaggle file not found: {kaggle_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_frame = build_final_dataset(nin_path, kaggle_path)
    structured_frame = build_structured_dataset(nin_path, kaggle_path)
    alias_frame = build_alias_dataset(structured_frame)
    final_frame.to_csv(output_path, index=False, encoding="utf-8-sig")
    structured_output_path.parent.mkdir(parents=True, exist_ok=True)
    structured_frame.to_csv(structured_output_path, index=False, encoding="utf-8-sig")
    alias_output_path.parent.mkdir(parents=True, exist_ok=True)
    alias_frame.to_csv(alias_output_path, index=False, encoding="utf-8-sig")

    manifest = build_version_manifest(
        version_tag=args.version_tag,
        nin_path=nin_path,
        kaggle_path=kaggle_path,
        final_path=output_path,
        structured_path=structured_output_path,
        alias_path=alias_output_path,
        structured_frame=structured_frame,
    )
    manifest_output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_output_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    safe_version = re.sub(r"[^a-zA-Z0-9._-]", "_", args.version_tag.strip())
    versioned_manifest_path = manifest_dir / f"dataset_{safe_version}.json"
    versioned_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    versioned_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved {len(final_frame)} rows to {output_path}")
    print(f"Saved {len(structured_frame)} rows to {structured_output_path}")
    print(f"Saved {len(alias_frame)} rows to {alias_output_path}")
    print(f"Saved dataset manifest to {manifest_output_path}")
    print(f"Saved versioned manifest to {versioned_manifest_path}")


if __name__ == "__main__":
    main()