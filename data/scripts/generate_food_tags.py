"""Automatic tag generation script for food items in final_nutrients_structured.csv."""

import csv
import os
import re
import unicodedata

def normalize_for_matching(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize('NFKC', text).lower()
    # Replace punctuation with spaces
    for char in ".,()[]{}/\\-_+*?!:;\"'":
        text = text.replace(char, " ")
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def generate_tags_for_row(row: dict[str, str]) -> list[str]:
    name_vi = row.get("name_vi") or ""
    name_en = row.get("canonical_name_en") or row.get("name_en") or ""
    cat = row.get("category") or ""
    
    # Normalize
    n_vi = normalize_for_matching(name_vi)
    n_en = normalize_for_matching(name_en)
    n_cat = normalize_for_matching(cat)

    def has_any(keywords: list[str]) -> bool:
        for kw in keywords:
            kw_norm = normalize_for_matching(kw)
            for t in (n_vi, n_en, n_cat):
                if f" {kw_norm} " in f" {t} ":
                    return True
        return False

    def has_any_name(keywords: list[str]) -> bool:
        for kw in keywords:
            kw_norm = normalize_for_matching(kw)
            for t in (n_vi, n_en):
                if f" {kw_norm} " in f" {t} ":
                    return True
        return False

    tags = []

    # 1. Allergens
    seafood_kws = ["cá", "tôm", "cua", "hải sản", "seafood", "fish", "shrimp", "crab", "salmon", "tuna", "herring", "mackerel", "mực", "bạch tuộc", "sò", "hàu", "nghêu", "ốc", "hến", "sứa", "chả cá"]
    if has_any(seafood_kws):
        tags.append("allergen_seafood")

    egg_kws = ["trứng", "egg", "eggs", "yolk", "egg white", "egg whites", "egg yolk", "lòng đỏ", "lòng trắng"]
    if has_any(egg_kws):
        tags.append("allergen_egg")

    peanut_kws = ["lạc", "đậu phộng", "peanut", "peanuts"]
    if has_any(peanut_kws):
        tags.append("allergen_peanut")

    milk_kws = ["sữa", "milk", "bơ", "butter", "cheese", "phô mai", "pho mai", "yogurt", "sữa chua", "whey", "lactose", "váng sữa", "sữa đặc"]
    if has_any(milk_kws):
        tags.append("allergen_milk")

    soy_kws = ["đậu nành", "đậu phụ", "tofu", "soy", "soya", "tào phớ"]
    if has_any(soy_kws):
        tags.append("allergen_soy")

    wheat_kws = ["lúa mì", "bột mì", "wheat", "gluten", "bánh mì", "bread"]
    if has_any(wheat_kws):
        tags.append("allergen_wheat")

    beef_kws = ["bò", "beef", "veal"]
    if has_any(beef_kws):
        tags.append("allergen_beef")

    pork_kws = ["heo", "lợn", "pork", "bacon", "lạp xưởng", "xúc xích"]
    if has_any(pork_kws):
        tags.append("allergen_pork")

    chicken_kws = ["gà", "chicken"]
    if has_any(chicken_kws):
        tags.append("allergen_chicken")

    duck_kws = ["vịt", "duck"]
    if has_any(duck_kws):
        tags.append("allergen_duck")

    # 2. Food Roles
    protein_cats = ["gia_cam", "thit_do", "hai_san", "trung", "sua_che_pham", "thịt gia cầm", "gia cầm", "thịt đỏ", "hải sản", "trứng", "sữa và chế phẩm", "sữa"]
    protein_kws = ["chicken", "gà", "beef", "bò", "pork", "heo", "fish", "cá", "salmon", "hồi", "duck", "vịt", "egg", "trứng", "yolk", "lòng đỏ", "egg white", "egg whites", "lòng trắng", "salami", "bacon", "turkey", "shrimp", "tôm", "crab", "cua", "cheese", "phô mai", "yogurt", "sữa chua"]
    if any(n_cat == normalize_for_matching(c) for c in protein_cats) or has_any(protein_kws):
        tags.append("role_protein")

    carb_cats = ["tinh_bot", "tinh bột"]
    carb_kws = ["rice", "cơm", "oat", "yến mạch", "bread", "bánh mì", "potato", "khoai tây", "cornstarch", "tinh bột", "popcorn", "cakes", "pudding", "ngũ cốc"]
    if any(n_cat == normalize_for_matching(c) for c in carb_cats) or has_any(carb_kws):
        tags.append("role_carb")

    fiber_cats = ["rau_cu", "trai_cay", "rau củ", "trái cây", "rau"]
    fiber_kws = ["cabbage", "cải", "vegetable", "rau", "salad", "xà lách", "onion", "hành", "fruit", "trái cây", "banana", "chuối", "muống", "bó xôi", "súp lơ", "nấm", "quả", "táo", "cam", "nho", "xoài"]
    if any(n_cat == normalize_for_matching(c) for c in fiber_cats) or has_any(fiber_kws):
        tags.append("role_fiber")

    # 3. Clean Protein (for gym)
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
                tags.append("clean_protein")

    # 4. Portion characteristics (Name-only matching)
    if has_any_name(["khô", "sấy", "dried"]):
        tags.append("is_dried")
    if has_any_name(["bột", "powder", "whey"]):
        tags.append("is_powder")
    if has_any_name(["hộp", "canned", "sốt cà chua", "pate", "lạp xưởng", "xúc xích"]):
        tags.append("is_processed")
    if has_any_name(["phô mai", "pho mai", "cheese", "bơ", "butter"]):
        tags.append("is_cheese_butter")
    if has_any_name(["sữa đặc", "condensed"]):
        tags.append("is_condensed_milk")
    if has_any_name(["tiết", "blood"]):
        tags.append("is_blood")

    dessert_cats = ["đồ_ăn_vặt", "đồ ăn vặt", "bánh_kẹo", "bánh kẹo", "tráng_miệng", "tráng miệng"]
    dessert_kws = ["bánh ngọt", "bánh kẹo", "chè", "dessert", "kẹo", "bim bim", "snack", "vặt", "tráng miệng"]
    if any(n_cat == normalize_for_matching(c) for c in dessert_cats) or has_any(dessert_kws):
        tags.append("is_dessert_snack")

    # 5. Suitability
    main_dish_cats = ["mon_chinh", "chao", "xoi", "banh_bao", "mon_nuoc", "banh_cuon", "banh_chung_banh_tet", "mon_an_che_bien", "mon_an_che_bien_san", "món chính", "cháo", "xôi", "bánh bao", "món nước", "bánh cuốn", "bánh chưng bánh tét", "món ăn chế biến", "món ăn chế biến sẵn"]
    if any(n_cat == normalize_for_matching(c) for c in main_dish_cats):
        tags.append("is_main_dish")

    return tags


def main():
    csv_path = "data/raw/final_nutrients_structured.csv"
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return

    print(f"Reading {csv_path}...")
    rows = []
    headers = []
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        for row in reader:
            rows.append(row)

    if "tags" not in headers:
        headers.append("tags")

    print(f"Processing {len(rows)} food rows...")
    tagged_count = 0
    for row in rows:
        tags = generate_tags_for_row(row)
        row["tags"] = ",".join(tags)
        if tags:
            tagged_count += 1

    print(f"Writing updated CSV back to {csv_path}...")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done! Tagged {tagged_count}/{len(rows)} food items.")

if __name__ == "__main__":
    main()
