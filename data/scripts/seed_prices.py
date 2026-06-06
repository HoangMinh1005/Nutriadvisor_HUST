"""Seed estimated food prices and categories using Gemini API.

This script reads crawled food items from 'nin_data_raw.csv', batches them,
and prompts Gemini to estimate a 'budget/student' market price per 100g 
in VND, along with an overarching category. It incorporates rate limit (HTTP 429)
backoff to avoid LLM failing midway.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DATA_PATH = ROOT_DIR / "data" / "raw" / "final_nutrients_structured.csv"
OUTPUT_PATH = ROOT_DIR / "data" / "seeded_prices.json"
SOURCE_FILTER = "NIN"

load_dotenv(ROOT_DIR / "backend" / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL_PRIMARY = os.getenv("GEMINI_MODEL_PRIMARY", "gemini-2.5-flash-lite")
GEMINI_MODEL_FALLBACKS = [
    model.strip()
    for model in os.getenv(
        "GEMINI_MODEL_FALLBACKS",
        "gemini-2.5-flash,gemini-2.0-flash-lite,gemini-2.0-flash",
    ).split(",")
    if model.strip()
]

SYSTEM_PROMPT = """Bạn là một chuyên gia dữ liệu dinh dưỡng tại Việt Nam.
Nhiệm vụ của bạn là ước lượng GIÁ THÀNH TRUNG BÌNH (đơn vị: VND) cho 100g thực phẩm thô/chưa chế biến tại thị trường bình dân (chợ dân sinh/siêu thị nhỏ) phục vụ cho đối tượng sinh viên. Đồng thời phân loại nhóm thực phẩm.

Hãy tính toán dựa trên danh sách thực phẩm được cung cấp.
Trả về một JSON object duy nhất, nơi keys là "canonical_key" và values là một định dạng Object:
{
    "canonical_key": {
    "price_100g": <giá_tiền_vnd_int>,
        "category": "<nhóm_ví_dụ: thịt_đỏ, rau_xanh, trái_cây, tinh_bột, trứng, sữa, cá_hải_sản, đồ_uống, gia_vị, hạt_các_loại>"
  }
}

Yêu cầu nghiêm ngặt: 
- Lấy chính xác tên thực phẩm gốc được truyền vào.
- Giá tiền phải là số nguyên (Integer).
- Chỉ trả ra MỘT JSON thuần tuý (JSON object). KHÔNG CÓ ký tự markdown định dạng ` ```json ` hay text thừa xung quanh.
"""

def load_food_records(raw_data_path: Path, source_filter: str) -> List[dict[str, str]]:
    records: list[dict[str, str]] = []
    if not raw_data_path.exists():
        print(f"File not found: {raw_data_path}")
        return records

    with open(raw_data_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("source", "").strip().upper() != source_filter:
                continue

            source_id = row.get("source_id", "").strip()
            name_vi = row.get("name_vi", "").strip()
            canonical_key = row.get("canonical_key", "").strip()

            if not source_id or not name_vi or not canonical_key:
                continue

            records.append(
                {
                    "source_id": source_id,
                    "name_vi": name_vi,
                    "canonical_key": canonical_key,
                }
            )

    return records

def chunk_list(items: List[str], chunk_size: int) -> List[List[str]]:
    return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]


def normalize_seed_key(key: str) -> str:
    return key.split("|")[0].strip() if key else key

def candidate_models() -> List[str]:
    models: List[str] = []
    for model in [GEMINI_MODEL_PRIMARY, *GEMINI_MODEL_FALLBACKS]:
        if model and model not in models:
            models.append(model)
    return models


def call_gemini(food_batch: List[dict[str, str]]) -> Dict[str, Any] | str | None:
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY is not set.")
        return None

    prompt_lines = [
        f"- {record['canonical_key']} | {record['name_vi']} | {record['source_id']}"
        for record in food_batch
    ]
    prompt = "Danh sách thực phẩm:\n" + "\n".join(prompt_lines)
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 1,
            "responseMimeType": "application/json",
        },
    }

    last_error: str | None = None
    for model_name in candidate_models():
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                print(f"Gemini success with model: {model_name}")
                return data
        except urllib.error.HTTPError as exc:
            last_error = f"HTTPError {exc.code} - {exc.reason}"
            print(f"Gemini API {last_error} on model {model_name}")
            if exc.code == 429:
                return "RATE_LIMIT"
            if exc.code in {400, 401, 403, 404}:
                continue
        except Exception as exc:
            last_error = str(exc)
            print(f"Gemini API Error on model {model_name}: {exc}")

    if last_error:
        print(f"All Gemini models failed for this batch. Last error: {last_error}")
    return None

def extract_json_from_response(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        # Remove code blocks if API still returned markdown despite instructions
        clean_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I | re.S).strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"JSON extraction failed: {e}")
        return {}


def normalize_seed_map(data: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        normalized[normalize_seed_key(key)] = value
    return normalized


def build_item_records(
    records: List[dict[str, str]],
    by_canonical_key: dict[str, Any],
    by_name: dict[str, Any],
    by_source_id: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for record in records:
        canonical_key = record["canonical_key"]
        name_vi = record["name_vi"]
        source_id = record["source_id"]
        info = by_canonical_key.get(canonical_key) or by_name.get(name_vi)
        if not info:
            continue

        item = {
            "source_id": source_id,
            "name_vi": name_vi,
            "canonical_key": canonical_key,
            "price_100g": info.get("price_100g"),
            "category": info.get("category"),
        }
        items.append(item)
        by_source_id[source_id] = item
        by_name.setdefault(name_vi, {"price_100g": info.get("price_100g"), "category": info.get("category")})
        by_canonical_key.setdefault(canonical_key, {"price_100g": info.get("price_100g"), "category": info.get("category")})

    return items


def compose_output(
    records: List[dict[str, str]],
    by_canonical_key: dict[str, Any],
    by_name: dict[str, Any],
    by_source_id: dict[str, Any],
    source_name: str,
) -> dict[str, Any]:
    items = build_item_records(records, by_canonical_key, by_name, by_source_id)
    categories: dict[str, list[int]] = {}
    for item in items:
        category = item.get("category", "khong_xac_dinh")
        price = int(item.get("price_100g") or 0)
        categories.setdefault(category, []).append(price)

    category_averages = {cat: int(sum(prices) / len(prices)) for cat, prices in categories.items() if prices}
    summary = {
        "source": source_name,
        "schema_version": 2,
        "total_source_records": len(records),
        "total_items": len(items),
        "unique_canonical_keys": len(by_canonical_key),
        "unique_names": len(by_name),
        "unique_source_ids": len(by_source_id),
        "global_average_100g": int(sum(category_averages.values()) / len(category_averages)) if category_averages else 15000,
        "category_count": len(category_averages),
    }

    return {
        "schema_version": 2,
        "summary": summary,
        "items": items,
        "indices": {
            "by_canonical_key": {k: {"price_100g": v.get("price_100g"), "category": v.get("category")} for k, v in by_canonical_key.items()},
            "by_name_vi": {k: {"price_100g": v.get("price_100g"), "category": v.get("category")} for k, v in by_name.items()},
            "by_source_id": by_source_id,
        },
    }


def load_existing_results(output_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    existing_by_canonical_key: dict[str, Any] = {}
    existing_by_name: dict[str, Any] = {}
    existing_by_source_id: dict[str, Any] = {}

    if not output_path.exists():
        return existing_by_canonical_key, existing_by_name, existing_by_source_id

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        print("Could not load existing file, starting fresh.")
        return existing_by_canonical_key, existing_by_name, existing_by_source_id

    if isinstance(loaded, dict) and loaded.get("schema_version") == 2 and isinstance(loaded.get("indices"), dict):
        indices = loaded.get("indices", {}) or {}
        existing_by_canonical_key = normalize_seed_map(indices.get("by_canonical_key", {}) or {})
        existing_by_name = normalize_seed_map(indices.get("by_name_vi", {}) or {})
        existing_by_source_id = indices.get("by_source_id", {}) or {}
        return existing_by_canonical_key, existing_by_name, existing_by_source_id

    if isinstance(loaded, dict) and "items_by_canonical_key" in loaded:
        existing_by_canonical_key = normalize_seed_map(loaded.get("items_by_canonical_key", {}) or {})
        existing_by_name = normalize_seed_map(loaded.get("items_by_name", {}) or {})
        existing_by_source_id = loaded.get("records_by_source_id", {}) or {}
        return existing_by_canonical_key, existing_by_name, existing_by_source_id

    if isinstance(loaded, dict):
        existing_by_name = loaded

    return existing_by_canonical_key, existing_by_name, existing_by_source_id

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed prices from Gemini API.")
    parser.add_argument("--batch-size", type=int, default=50, help="Number of items per Gemini prompt.")
    parser.add_argument("--limit", type=int, default=0, help="Max items to process mode (0 = all).")
    parser.add_argument("--raw-data", type=str, default=str(RAW_DATA_PATH), help="Path to raw CSV dataset.")
    parser.add_argument("--output", type=str, default=str(OUTPUT_PATH), help="Path to output seeded JSON.")
    parser.add_argument("--source", type=str, default=SOURCE_FILTER, help="Source database filter (e.g. NIN, VDD).")
    args = parser.parse_args()

    raw_data_path = Path(args.raw_data)
    output_path = Path(args.output)
    source_filter = args.source.strip().upper()

    existing_by_canonical_key, existing_by_name, existing_by_source_id = load_existing_results(output_path)

    all_records = load_food_records(raw_data_path, source_filter)
    print(f"Total {source_filter} records in structured CSV: {len(all_records)}")

    unique_records_by_key: dict[str, dict[str, str]] = {}
    for record in all_records:
        key = record["canonical_key"]
        if key not in unique_records_by_key:
            unique_records_by_key[key] = record

    print(f"Unique canonical dishes to seed: {len(unique_records_by_key)}")

    foods_to_process = [
        record
        for record in unique_records_by_key.values()
        if record["canonical_key"] not in existing_by_canonical_key and record["name_vi"] not in existing_by_name
    ]
    print(f"Unique canonical dishes left to process: {len(foods_to_process)}")
    
    if args.limit > 0:
        foods_to_process = foods_to_process[:args.limit]
        print(f"Limiting to {args.limit} foods.")

    batches = chunk_list(foods_to_process, args.batch_size) if foods_to_process else []
    if not batches:
        print("Nothing to process.")
    else:
        print(f"Total batches to run: {len(batches)}")

    if not existing_by_canonical_key:
        existing_by_canonical_key = {}
    if not existing_by_name:
        existing_by_name = {}
    if not existing_by_source_id:
        existing_by_source_id = {}

    for i, batch in enumerate(batches, start=1):
        print(f"Processing batch {i}/{len(batches)} ({len(batch)} items)...")
        
        retries = 3
        success = False
        
        while retries > 0 and not success:
            resp = call_gemini(batch)
            if resp == "RATE_LIMIT":
                wait_time = (4 - retries) * 15
                print(f"Rate limited. Waiting {wait_time}s...")
                time.sleep(wait_time)
                retries -= 1
            elif resp is None:
                print("Failed batch due to generic API error.")
                retries -= 1
                time.sleep(5)
            else:
                parsed = normalize_seed_map(extract_json_from_response(resp))
                if parsed:
                    existing_by_canonical_key.update(parsed)
                    success = True
                else:
                    print("Failed to parse JSON response. Retrying...")
                    retries -= 1
        
        if success:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(
                    compose_output(all_records, existing_by_canonical_key, existing_by_name, existing_by_source_id, source_filter),
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            time.sleep(2) # Modest sleep to avoid 429
        else:
            print(f"Batch {i} completely failed after retries. Aborting to save progress.")
            break

    # Expand canonical price estimates back onto every source record.
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(
            compose_output(all_records, existing_by_canonical_key, existing_by_name, existing_by_source_id, source_filter),
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Done. Processed results saved to {output_path}")
    
    # Sanity checks
    print("\n--- Sanity Check ---")
    suspects = 0
    categories = {}
    
    final_output = compose_output(all_records, existing_by_canonical_key, existing_by_name, existing_by_source_id, source_filter)

    for item in final_output["items"]:
        price = item.get("price_100g", 0)
        category = item.get("category", "khong_xac_dinh")
        food_name = item.get("name_vi", item.get("canonical_key", "Unknown"))
        
        if category not in categories:
            categories[category] = []
        categories[category].append(price)
        
        if price < 500 or price > 200000:
            print(f"⚠️ SUSPECT PRICE: '{food_name}' priced at {price} VND/100g")
            suspects += 1
            
    if suspects == 0:
        print("All extracted prices are within normal ranges (500 - 200,000 VND).")
    else:
        print(f"Found {suspects} suspicious prices. Please review the JSON manually.")

    # Calculate average category prices and build price_defaults.json
    print("\n--- Generating Price Defaults ---")
    category_averages = {}
    for cat, prices in categories.items():
        if prices:
            category_averages[cat] = int(sum(prices) / len(prices))
    
    defaults_path = raw_data_path.parent.parent / "price_defaults.json"
    
    price_defaults = {
        "schema_version": 2,
        "summary": final_output["summary"],
        "items": final_output["items"],
        "indices": final_output["indices"],
        "global_average_100g": final_output["summary"]["global_average_100g"],
        "categories": category_averages,
    }
    
    with open(defaults_path, "w", encoding="utf-8") as f:
        json.dump(price_defaults, f, ensure_ascii=False, indent=2)
        
    print(f"Successfully computed averages and built {defaults_path}")


if __name__ == "__main__":
    main()