"""Load structured nutrition dataset and aliases into PostgreSQL.

Usage:
    python data/scripts/load_structured_to_db.py --version-tag v1.1.0
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STRUCTURED_PATH = ROOT_DIR / "data" / "raw" / "viendinhduong_nutrients.csv"
DEFAULT_ALIAS_PATH = ROOT_DIR / "data" / "raw" / "food_aliases_vi.csv"
DEFAULT_MANIFEST_PATH = ROOT_DIR / "data" / "raw" / "dataset_version_manifest.json"

load_dotenv(ROOT_DIR / "backend" / ".env")
load_dotenv(ROOT_DIR / ".env")

import sys
sys.path.insert(0, str(ROOT_DIR))
from csp.classification import classify_food


def _clean_text(value: object) -> str:
    """Normalize raw scalar values to clean text, collapsing null-like strings to empty."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "null", "none"}:
        return ""
    return text


def _to_float(value: object) -> float:
    """Safely parse numeric inputs from CSV; return 0.0 when missing or invalid."""
    text = _clean_text(value)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _to_bool(value: object) -> bool:
    """Convert common truthy text flags from CSV into boolean values."""
    text = _clean_text(value).lower()
    return text in {"true", "1", "yes", "y"}


def _database_url() -> str:
    """Read DATABASE_URL from environment and fail fast if it is not configured."""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return db_url


def _load_csv(path: Path) -> list[dict[str, str]]:
    """Load a UTF-8 CSV file into a list of dict rows using header columns."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _dedupe_rows_by_canonical_key(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep the first row for each canonical_key so inserted IDs stay contiguous."""
    deduped_rows: list[dict[str, str]] = []
    seen_keys: set[str] = set()

    for row in rows:
        canonical_key = _clean_text(row.get("canonical_key"))
        if not canonical_key or canonical_key in seen_keys:
            continue
        seen_keys.add(canonical_key)
        deduped_rows.append(row)

    return deduped_rows


def _reset_food_tables(cur: psycopg.Cursor) -> None:
    """Clear food-related tables and restart identities before a clean reload."""
    cur.execute(
        """
        TRUNCATE TABLE
            food_source_rows,
            food_aliases,
            food_nutrients,
            meal_plans,
            food_search_logs,
            foods
        RESTART IDENTITY CASCADE;
        """
    )


def _load_source_rows(
    cur: psycopg.Cursor,
    rows: list[dict[str, str]],
    dataset_version_id: int,
    source_name: str,
    source_file: str,
) -> None:
    """Persist every raw row before canonical deduplication for traceability."""
    for row_number, row in enumerate(rows, start=1):
        cur.execute(
            """
            INSERT INTO food_source_rows (
                dataset_version_id, source_name, source_file, source_row_number,
                canonical_key, raw_payload
            ) VALUES (%s,%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT (dataset_version_id, source_name, source_file, source_row_number)
            DO UPDATE SET
                canonical_key = EXCLUDED.canonical_key,
                raw_payload = EXCLUDED.raw_payload;
            """,
            (
                dataset_version_id,
                source_name,
                source_file,
                row_number,
                _clean_text(row.get("canonical_key")),
                json.dumps(row, ensure_ascii=False),
            ),
        )


def _ensure_dataset_version(cur: psycopg.Cursor, version_tag: str, manifest_path: Path) -> int:
    """Upsert dataset version metadata and return its dataset_version_id."""
    manifest_text = manifest_path.read_text(encoding="utf-8") if manifest_path.exists() else "{}"
    source_manifest = json.loads(manifest_text)

    cur.execute(
        """
        INSERT INTO dataset_versions (version_tag, source_manifest, notes, source_hash)
        VALUES (%s, %s::jsonb, %s, md5(%s))
        ON CONFLICT (version_tag)
        DO UPDATE SET
            source_manifest = EXCLUDED.source_manifest,
            notes = EXCLUDED.notes,
            source_hash = EXCLUDED.source_hash,
            generated_at = NOW()
        RETURNING dataset_version_id;
        """,
        (
            version_tag,
            json.dumps(source_manifest, ensure_ascii=False),
            "Imported from structured CSV loader",
            manifest_text,
        ),
    )
    return int(cur.fetchone()[0])


def get_food_group_code(category: str, name_vi: str, tags: list[str]) -> str:
    category = category.strip()
    name_vi = name_vi.lower()

    if category == "Sữa và sản phẩm chế biến":
        return "sua_che_pham"
    elif category == "Ngũ cốc và sản phẩm chế biến":
        return "tinh_bot"
    elif category == "Đồ hộp":
        # Check name for meat/fish
        if any(k in name_vi for k in ["cá", "tôm", "trích", "thu", "nục", "ngừ", "hải sản"]):
            return "hai_san"
        elif any(k in name_vi for k in ["bò", "heo", "lợn", "pork", "beef"]):
            return "thit_do"
        elif any(k in name_vi for k in ["gà", "vịt", "chicken", "duck"]):
            return "gia_cam"
        return "khac"
    elif category == "Đồ ngọt (đường, bánh, mứt, kẹo)":
        if "trứng" in name_vi:
            return "trung"
        return "khac"
    elif category == "Bơ, mỡ":
        return "khac"
    elif category == "Gia vị, nước chấm":
        return "khac"
    elif category == "Nước giải khát":
        return "khac"
    elif category == "Rau, quả và sản phẩm chế biến":
        # Check tags or name to see if it's fruit
        if "role_fiber" in tags or any(k in name_vi for k in ["chuối", "dứa", "mận", "nhãn", "vải", "cam", "bưởi", "xoài", "táo", "lê", "đu đủ", "dưa", "ổi", "nho", "bơ", "hồng", "quýt"]):
            return "trai_cay"
        return "rau_cu"
    elif category == "Thịt, thủy sản và sản phẩm chế biến":
        if any(k in name_vi for k in ["gà", "vịt", "chim", "ngan"]):
            return "gia_cam"
        elif any(k in name_vi for k in ["cá", "tôm", "cua", "ốc", "hến", "sò", "mực", "lươn", "trạch", "ếch"]):
            return "hai_san"
        elif any(k in name_vi for k in ["trứng"]):
            return "trung"
        else:
            return "thit_do"
    
    return "khac"

# check_category and classify_food_row removed and imported from csp.classification


def _load_price_defaults() -> tuple[int, dict[str, int]]:
    price_path = ROOT_DIR / "data" / "price_defaults_2.json"
    if not price_path.exists():
        print(f"Warning: {price_path} not found. Using default price 15000 VND/100g.")
        return 15000, {}
    try:
        with open(price_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        global_avg = data.get("global_average_100g", 15000)
        price_map = {}
        for item in data.get("items", []):
            key = item.get("canonical_key")
            price = item.get("price_100g")
            if key and price is not None:
                price_map[key] = int(price)
        return global_avg, price_map
    except Exception as e:
        print(f"Error loading price defaults: {e}. Using default price 15000 VND/100g.")
        return 15000, {}

def _load_foods(cur: psycopg.Cursor, rows: list[dict[str, str]], dataset_version_id: int, price_map: dict[str, int], global_avg: int) -> dict[str, int]:
    """Insert canonical foods with contiguous IDs, then load matching nutrient vectors."""
    unique_rows = _dedupe_rows_by_canonical_key(rows)

    cur.execute("SELECT group_code, food_group_id FROM food_groups;")
    group_map = {r[0]: r[1] for r in cur.fetchall()}

    food_id_by_key: dict[str, int] = {}

    for next_food_id, row in enumerate(unique_rows, start=1):
        canonical_key = _clean_text(row.get("canonical_key"))
        if not canonical_key:
            continue

        raw_tags = _clean_text(row.get("tags"))
        tags = [t.strip().lower() for t in raw_tags.split(",") if t.strip()] if raw_tags else []
        
        category = _clean_text(row.get("category"))
        name_vi = _clean_text(row.get("name_vi"))
        group_code = get_food_group_code(category, name_vi, tags)
        food_group_id = group_map.get(group_code, group_map.get("khac"))

        price = price_map.get(canonical_key, global_avg)
        price = price_map.get(canonical_key, global_avg)
        from csp.classification import get_dynamic_tags
        food_data = {
            "name_vi": name_vi,
            "category": category,
            "tags": set(tags)
        }
        full_tags = get_dynamic_tags(food_data).union(tags)
        food_data["tags"] = full_tags
        meal_role = classify_food(food_data)

        cur.execute(
            """
            INSERT INTO foods (
                food_id, canonical_key, canonical_name_en, name_vi, food_group_id,
                source_name, source_priority, source_food_id, dataset_version_id,
                confidence_score, is_estimated, price_100g_vnd, tags, meal_role
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (canonical_key)
            DO UPDATE SET
                canonical_name_en = EXCLUDED.canonical_name_en,
                name_vi = EXCLUDED.name_vi,
                food_group_id = EXCLUDED.food_group_id,
                source_name = EXCLUDED.source_name,
                source_priority = EXCLUDED.source_priority,
                source_food_id = EXCLUDED.source_food_id,
                dataset_version_id = EXCLUDED.dataset_version_id,
                confidence_score = EXCLUDED.confidence_score,
                is_estimated = EXCLUDED.is_estimated,
                price_100g_vnd = EXCLUDED.price_100g_vnd,
                tags = EXCLUDED.tags,
                meal_role = EXCLUDED.meal_role,
                updated_at = NOW();
            """,
            (
                next_food_id,
                canonical_key,
                _clean_text(row.get("canonical_name_en") or row.get("name_en")),
                name_vi,
                food_group_id,
                _clean_text(row.get("source")) or "VDD",
                int(_to_float(row.get("source_priority")) or 1),
                _clean_text(row.get("source_id")),
                dataset_version_id,
                _to_float(row.get("confidence_score")) or 1.0,
                _to_bool(row.get("is_estimated")),
                price,
                list(full_tags),
                meal_role,
            ),
        )
        food_id_by_key[canonical_key] = next_food_id

    for row in unique_rows:
        canonical_key = _clean_text(row.get("canonical_key"))
        food_id = food_id_by_key.get(canonical_key)
        if not food_id:
            continue

        cur.execute(
            """
            INSERT INTO food_nutrients (
                food_id, basis_amount, basis_unit, energy_kcal, protein_g, fat_g,
                carbs_g, vitamin_a_mcg, beta_carotene_mcg, vitamin_c_mg, calcium_mg,
                iron_mg, zinc_mg, sodium_mg, cholesterol_mg, magnesium_mg, transfat_mg,
                nutrient_source, nutrient_confidence, dataset_version_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (food_id) DO UPDATE SET
                basis_amount = EXCLUDED.basis_amount,
                basis_unit = EXCLUDED.basis_unit,
                energy_kcal = EXCLUDED.energy_kcal,
                protein_g = EXCLUDED.protein_g,
                fat_g = EXCLUDED.fat_g,
                carbs_g = EXCLUDED.carbs_g,
                vitamin_a_mcg = EXCLUDED.vitamin_a_mcg,
                beta_carotene_mcg = EXCLUDED.beta_carotene_mcg,
                vitamin_c_mg = EXCLUDED.vitamin_c_mg,
                calcium_mg = EXCLUDED.calcium_mg,
                iron_mg = EXCLUDED.iron_mg,
                zinc_mg = EXCLUDED.zinc_mg,
                sodium_mg = EXCLUDED.sodium_mg,
                cholesterol_mg = EXCLUDED.cholesterol_mg,
                magnesium_mg = EXCLUDED.magnesium_mg,
                transfat_mg = EXCLUDED.transfat_mg,
                nutrient_source = EXCLUDED.nutrient_source,
                nutrient_confidence = EXCLUDED.nutrient_confidence,
                dataset_version_id = EXCLUDED.dataset_version_id,
                updated_at = NOW();
            """,
            (
                food_id,
                100.0,
                "g",
                _to_float(row.get("nang_luong_kcal")),
                _to_float(row.get("chat_dam_g")),
                _to_float(row.get("chat_beo_g")),
                _to_float(row.get("chat_bot_duong_g")),
                _to_float(row.get("vitamin_a_mcg")),
                _to_float(row.get("beta_carotene_mcg")),
                _to_float(row.get("vitamin_c_mg")),
                _to_float(row.get("calcium_mg")),
                _to_float(row.get("iron_mg")),
                _to_float(row.get("zinc_mg")),
                _to_float(row.get("sodium_mg")),
                _to_float(row.get("cholesterol_mg")),
                _to_float(row.get("magnesium_mg")),
                _to_float(row.get("transfat_mg")),
                _clean_text(row.get("source")) or "VDD",
                _to_float(row.get("confidence_score")) or 1.0,
                dataset_version_id,
            ),
        )
    return food_id_by_key


def _load_aliases(cur: psycopg.Cursor, alias_rows: list[dict[str, str]]) -> None:
    """Upsert searchable aliases and map each alias to existing canonical foods."""
    values = []
    for row in alias_rows:
        values.append(
            (
                _clean_text(row.get("canonical_key")),
                _clean_text(row.get("alias_text")),
                _clean_text(row.get("alias_lang")) or "vi",
                _clean_text(row.get("alias_type")) or "display",
                _to_bool(row.get("is_preferred")),
                _clean_text(row.get("source")) or "VDD",
                int(_to_float(row.get("source_priority")) or 1),
            )
        )

    for v in values:
        canonical_key = v[0]
        alias_text = v[1]
        alias_lang = v[2]
        alias_type = v[3]
        is_preferred = v[4]
        source_name = v[5]
        source_priority = v[6]

        cur.execute("SELECT food_id FROM foods WHERE canonical_key = %s", (canonical_key,))
        row = cur.fetchone()
        if not row:
            continue
        food_id = row[0]
        cur.execute(
            """
            INSERT INTO food_aliases (
                food_id, alias_text, alias_lang, alias_type, is_preferred, source_name, source_priority
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (food_id, alias_lang, alias_text)
            DO UPDATE SET
                alias_type = EXCLUDED.alias_type,
                is_preferred = EXCLUDED.is_preferred,
                source_name = EXCLUDED.source_name,
                source_priority = EXCLUDED.source_priority;
            """,
            (food_id, alias_text, alias_lang, alias_type, is_preferred, source_name, source_priority),
        )


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for structured, alias, manifest paths, and version tag."""
    parser = argparse.ArgumentParser(description="Load structured nutrition data into PostgreSQL")
    parser.add_argument("--structured", default=str(DEFAULT_STRUCTURED_PATH), help="Path to viendinhduong_nutrients.csv")
    parser.add_argument("--aliases", default=str(DEFAULT_ALIAS_PATH), help="Path to food_aliases_vi.csv")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Path to dataset_version_manifest.json")
    parser.add_argument("--version-tag", default="v1.1.0", help="Dataset version tag")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Truncate food-related tables and restart identities before loading",
    )
    return parser.parse_args()


def main() -> None:
    """Run end-to-end loader: validate files, read CSVs, and write into PostgreSQL."""
    args = parse_args()
    structured_path = Path(args.structured)
    aliases_path = Path(args.aliases)
    manifest_path = Path(args.manifest)

    if not structured_path.exists():
        raise FileNotFoundError(f"Structured data not found: {structured_path}")
    if not aliases_path.exists():
        raise FileNotFoundError(f"Alias data not found: {aliases_path}")

    rows = _load_csv(structured_path)
    alias_rows = _load_csv(aliases_path)

    global_avg, price_map = _load_price_defaults()

    with psycopg.connect(_database_url()) as conn:
        with conn.cursor() as cur:
            if args.reset:
                _reset_food_tables(cur)
            dataset_version_id = _ensure_dataset_version(cur, args.version_tag, manifest_path)
            _load_source_rows(
                cur,
                rows,
                dataset_version_id,
                source_name="structured_csv",
                source_file=structured_path.name,
            )
            food_id_by_key = _load_foods(cur, rows, dataset_version_id, price_map, global_avg)
            _load_aliases(cur, alias_rows)
        conn.commit()

    print(f"Loaded {len(rows)} structured rows and {len(alias_rows)} aliases into PostgreSQL")
    print(f"Dataset version: {args.version_tag}")


if __name__ == "__main__":
    main()
