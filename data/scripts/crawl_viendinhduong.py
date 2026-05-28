"""Crawl nutrition data from viendinhduong.vn.

The page is driven by public JSON endpoints. Selenium is used to open the page
and trigger the search UI once, while the actual crawl reads the API directly.
This is much faster and far more reliable than scraping the rendered table.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import requests
from selenium import webdriver
from selenium.webdriver import ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

URL = "https://viendinhduong.vn/vi/cong-cu-va-tien-ich/gia-tri-dinh-duong-mon-an"
API_DATA_URL = "https://viendinhduong.vn/api/fe/tool/getPageFoodData"
API_CATEGORY_URL = "https://viendinhduong.vn/api/fe/tool/apiGetListFoodCategory"
ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT_DIR / "data" / "raw" / "nin_data_raw.csv"

SEARCH_BUTTON_SELECTOR = "button.btn-search"


def build_driver(headless: bool = False) -> webdriver.Chrome:
    """Build a Chrome driver with anti-bot friendly defaults."""
    options = ChromeOptions()
    if headless:
        options.add_argument("--headless=new")

    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    options.page_load_strategy = "normal"
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        },
    )
    return driver


def open_page_and_click_search(headless: bool) -> None:
    """Open the page in Selenium and trigger the default search UI once."""
    driver = build_driver(headless=headless)
    wait = WebDriverWait(driver, 20)
    try:
        driver.get(URL)
        search_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, SEARCH_BUTTON_SELECTOR)))
        driver.execute_script("arguments[0].click();", search_btn)
    finally:
        driver.quit()


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": URL,
        }
    )
    return session


def fetch_categories(session: requests.Session) -> Dict[str, str]:
    response = session.get(API_CATEGORY_URL, timeout=30)
    response.raise_for_status()
    categories = response.json()
    return {item["_id"]: item["name"] for item in categories}


def fetch_page(session: requests.Session, page: int, page_size: int = 15, energy: int = 0, max_retries: int = 3) -> Dict[str, Any]:
    """Fetch a single page of food data with retry logic."""
    for attempt in range(max_retries):
        try:
            response = session.get(
                API_DATA_URL,
                params={"page": page, "pageSize": page_size, "energy": energy},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5  # 5s, 10s, 15s
                print(f"Timeout on page {page}, retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise


def component_map(components: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for item in components:
        key = str(item.get("key", "")).strip()
        if key:
            mapping[key] = item
    return mapping


def _safe_float(value: Any) -> float | None:
    """Safely convert value to float, returning None if empty or invalid."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_food_item(item: Dict[str, Any], category_map: Dict[str, str], page: int) -> Dict[str, Any]:
    """Parse a food item from API response, extracting all nutrients."""
    components = component_map(item.get("nutritional_components", []))
    category_id = str(item.get("category_id", "")).strip()

    return {
        # Metadata
        "page": page,
        "stt": "",
        "ma_so": item.get("code", ""),
        "nhom": category_map.get(category_id, ""),
        "ten_mon_an": item.get("name_vi", ""),
        "ten_mon_an_en": item.get("name_en", ""),
        # Macronutrients
        "nang_luong_kcal": _safe_float(components.get("nang-luong", {}).get("amount")),
        "chat_dam_g": _safe_float(components.get("chat-dam", {}).get("amount")),
        "chat_beo_g": _safe_float(components.get("chat-beo", {}).get("amount")),
        "chat_bot_duong_g": _safe_float(components.get("chat-bot-duong", {}).get("amount")),
        # Micronutrients
        "vitamin_a_mcg": _safe_float(components.get("vitamin-a", {}).get("amount")),
        "beta_carotene_mcg": _safe_float(components.get("beta-caroten", {}).get("amount")),
        "vitamin_c_mg": _safe_float(components.get("vitamin-c", {}).get("amount")),
        "calcium_mg": _safe_float(components.get("calcium", {}).get("amount")),
        "iron_mg": _safe_float(components.get("iron", {}).get("amount")),
        "zinc_mg": _safe_float(components.get("zinc", {}).get("amount")),
        "sodium_mg": _safe_float(components.get("natri", {}).get("amount")),
        "cholesterol_mg": _safe_float(components.get("cholesterol", {}).get("amount")),
        "magnesium_mg": _safe_float(components.get("magnesium", {}).get("amount")),
        "transfat_mg": _safe_float(components.get("transfat", {}).get("amount")),
    }


def crawl(headless: bool, output_path: Path) -> pd.DataFrame:
    """Crawl all pages and persist the result to CSV."""
    # Use Selenium once to satisfy the interactive workflow and warm up the page.
    open_page_and_click_search(headless=headless)

    session = make_session()
    category_map = fetch_categories(session)
    first_page = fetch_page(session, page=1, page_size=15, energy=0)
    last_page = int(first_page.get("last_page", 1))

    all_rows: List[Dict[str, Any]] = []

    for page in range(1, last_page + 1):
        payload = first_page if page == 1 else fetch_page(session, page=page, page_size=15, energy=0)
        page_rows = [parse_food_item(item, category_map, page) for item in payload.get("data", [])]

        # Fill STT based on row order within each API page.
        for index, row in enumerate(page_rows, start=1):
            row["stt"] = index

        all_rows.extend(page_rows)
        print(f"Fetched page {page}/{last_page} - Total rows: {len(all_rows)}")

    # Write CSV once at the end
    df = pd.DataFrame(all_rows).drop_duplicates()
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl nutrition data from viendinhduong.vn")
    parser.add_argument("--headless", action="store_true", help="Run Chrome in headless mode")
    parser.add_argument(
        "--output",
        default=str(OUTPUT_PATH),
        help="CSV output path (default: data/raw/nin_data_raw.csv)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df = crawl(headless=args.headless, output_path=output_path)
    print(f"Saved {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main()
