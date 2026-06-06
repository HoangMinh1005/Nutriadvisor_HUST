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


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STRUCTURED_PATH = ROOT_DIR / "data" / "raw" / "final_nutrients_structured.csv"
DEFAULT_ALIAS_PATH = ROOT_DIR / "data" / "raw" / "food_aliases_vi.csv"
DEFAULT_MANIFEST_PATH = ROOT_DIR / "data" / "raw" / "dataset_version_manifest.json"

FOOD_GROUP_MAP = {
    "Gia cầm": "gia_cam",
    "Thịt đỏ": "thit_do",
    "Hải sản": "hai_san",
    "Rau củ": "rau_cu",
    "Tinh bột": "tinh_bot",
    "Hạt": "hat",
    "Trái cây": "trai_cay",
    "Sữa và chế phẩm": "sua_che_pham",
    "Trứng": "trung",
    "Khác": "khac",
}


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
            food_tag_mapping,
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


def _load_foods(cur: psycopg.Cursor, rows: list[dict[str, str]], dataset_version_id: int) -> None:
    """Insert canonical foods with contiguous IDs, then load matching nutrient vectors."""
    unique_rows = _dedupe_rows_by_canonical_key(rows)

    cur.execute("SELECT group_code, food_group_id FROM food_groups;")
    group_map = {r[0]: r[1] for r in cur.fetchall()}

    food_id_by_key: dict[str, int] = {}

    for next_food_id, row in enumerate(unique_rows, start=1):
        canonical_key = _clean_text(row.get("canonical_key"))
        if not canonical_key:
            continue

        group_code = FOOD_GROUP_MAP.get(_clean_text(row.get("category")), "khac")
        food_group_id = group_map.get(group_code)

        cur.execute(
            """
            INSERT INTO foods (
                food_id, canonical_key, canonical_name_en, name_vi, food_group_id,
                source_name, source_priority, source_food_id, dataset_version_id,
                confidence_score, is_estimated
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
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
                updated_at = NOW();
            """,
            (
                next_food_id,
                canonical_key,
                _clean_text(row.get("canonical_name_en") or row.get("name_en")),
                _clean_text(row.get("name_vi")),
                food_group_id,
                _clean_text(row.get("source")) or "Kaggle",
                int(_to_float(row.get("source_priority")) or 2),
                _clean_text(row.get("source_id")),
                dataset_version_id,
                _to_float(row.get("confidence_score")) or 0.65,
                _to_bool(row.get("is_estimated")),
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
                _clean_text(row.get("source")) or "Kaggle",
                _to_float(row.get("confidence_score")) or 0.65,
                dataset_version_id,
            ),
        )
    return food_id_by_key




def _load_tags(cur: psycopg.Cursor, rows: list[dict[str, str]], food_id_by_key: dict[str, int]) -> None:
    """Load tags from CSV rows, insert unique ones into food_tags, and map them in food_tag_mapping."""
    # First, collect all unique tag codes from the CSV
    unique_tags = set()
    for row in rows:
        tags_str = _clean_text(row.get("tags"))
        if tags_str:
            for tag in tags_str.split(","):
                tag = tag.strip().lower()
                if tag:
                    unique_tags.add(tag)

    # Insert unique tags into food_tags table
    for tag_code in sorted(unique_tags):
        tag_name = tag_code.replace("_", " ").capitalize()
        cur.execute(
            """
            INSERT INTO food_tags (tag_code, tag_name, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (tag_code) DO NOTHING;
            """,
            (tag_code, tag_name, f"Automatically generated tag for {tag_name}"),
        )

    # Select all tag ids to map code -> tag_id
    cur.execute("SELECT tag_code, tag_id FROM food_tags;")
    tag_id_map = {r[0]: r[1] for r in cur.fetchall()}

    # Insert mappings
    for row in rows:
        canonical_key = _clean_text(row.get("canonical_key"))
        food_id = food_id_by_key.get(canonical_key)
        if not food_id:
            continue

        tags_str = _clean_text(row.get("tags"))
        if not tags_str:
            continue

        for tag_code in tags_str.split(","):
            tag_code = tag_code.strip().lower()
            tag_id = tag_id_map.get(tag_code)
            if not tag_id:
                continue

            cur.execute(
                """
                INSERT INTO food_tag_mapping (food_id, tag_id, confidence, assigned_by)
                VALUES (%s, %s, 1.000, 'rule_engine')
                ON CONFLICT (food_id, tag_id) DO NOTHING;
                """,
                (food_id, tag_id),
            )


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
                _clean_text(row.get("source")) or "NIN",
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
    parser.add_argument("--structured", default=str(DEFAULT_STRUCTURED_PATH), help="Path to final_nutrients_structured.csv")
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
            food_id_by_key = _load_foods(cur, rows, dataset_version_id)
            _load_tags(cur, rows, food_id_by_key)
            _load_aliases(cur, alias_rows)
        conn.commit()

    print(f"Loaded {len(rows)} structured rows and {len(alias_rows)} aliases into PostgreSQL")
    print(f"Dataset version: {args.version_tag}")


if __name__ == "__main__":
    main()
