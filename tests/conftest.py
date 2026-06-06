"""Pytest configuration and shared fixtures for all tests."""

import json
import os
from pathlib import Path
from typing import Generator

import psycopg
import pytest
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / "backend" / ".env")
load_dotenv(ROOT_DIR / ".env")


def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "unit: unit tests (no DB required)")
    config.addinivalue_line("markers", "integration: integration tests (DB required)")
    config.addinivalue_line("markers", "slow: slow running tests")
    config.addinivalue_line("markers", "db: tests requiring database")
    config.addinivalue_line("markers", "api: tests requiring API")


def pytest_collection_modifyitems(config, items):
    """Auto-mark tests based on file location."""
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def database_url() -> str:
    """Get DATABASE_URL from environment."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL not configured. Set it before running tests:\n"
            'export DATABASE_URL="postgresql://nutri_user:minhdt@localhost:5433/nutri_advisor"'
        )
    return url


@pytest.fixture(scope="session")
def db_connection(database_url: str) -> Generator[psycopg.Connection, None, None]:
    """Establish PostgreSQL connection for test session."""
    try:
        conn = psycopg.connect(database_url)
        conn.autocommit = True
        yield conn
    finally:
        conn.close()


@pytest.fixture
def db_cursor(db_connection: psycopg.Connection) -> Generator[psycopg.Cursor, None, None]:
    """Provide a fresh cursor for each test."""
    cursor = db_connection.cursor()
    yield cursor
    cursor.close()


@pytest.fixture
def sample_csv_rows() -> list[dict[str, str]]:
    """Provide sample CSV rows for testing deduplication."""
    return [
        {
            "canonical_key": "beef",
            "canonical_name_en": "Beef",
            "name_vi": "Thịt bò",
            "category": "Thịt đỏ",
            "source": "NIN",
            "source_priority": "1",
            "source_id": "NIN_001",
            "confidence_score": "0.95",
            "is_estimated": "false",
            "nang_luong_kcal": "250",
            "chat_dam_g": "26",
            "chat_beo_g": "15",
            "chat_bot_duong_g": "0",
            "vitamin_a_mcg": "0",
            "beta_carotene_mcg": "0",
            "vitamin_c_mg": "0",
            "calcium_mg": "10",
            "iron_mg": "2.6",
            "zinc_mg": "6.31",
            "sodium_mg": "75",
            "cholesterol_mg": "86",
            "magnesium_mg": "19",
            "transfat_mg": "0.3",
        },
        {
            "canonical_key": "beef",  # duplicate
            "canonical_name_en": "Beef (variant)",
            "name_vi": "Thịt bò (biến thể)",
            "category": "Thịt đỏ",
            "source": "Kaggle",
            "source_priority": "2",
            "source_id": "KG_999",
            "confidence_score": "0.80",
            "is_estimated": "true",
            "nang_luong_kcal": "245",
            "chat_dam_g": "25",
            "chat_beo_g": "14",
            "chat_bot_duong_g": "0",
            "vitamin_a_mcg": "0",
            "beta_carotene_mcg": "0",
            "vitamin_c_mg": "0",
            "calcium_mg": "9",
            "iron_mg": "2.5",
            "zinc_mg": "6.0",
            "sodium_mg": "70",
            "cholesterol_mg": "85",
            "magnesium_mg": "18",
            "transfat_mg": "0.2",
        },
        {
            "canonical_key": "chicken",
            "canonical_name_en": "Chicken Breast",
            "name_vi": "Ngực gà",
            "category": "Gia cầm",
            "source": "NIN",
            "source_priority": "1",
            "source_id": "NIN_002",
            "confidence_score": "0.92",
            "is_estimated": "false",
            "nang_luong_kcal": "165",
            "chat_dam_g": "31",
            "chat_beo_g": "3.6",
            "chat_bot_duong_g": "0",
            "vitamin_a_mcg": "5",
            "beta_carotene_mcg": "0",
            "vitamin_c_mg": "0",
            "calcium_mg": "13",
            "iron_mg": "0.9",
            "zinc_mg": "0.9",
            "sodium_mg": "74",
            "cholesterol_mg": "85",
            "magnesium_mg": "29",
            "transfat_mg": "0.1",
        },
        {
            "canonical_key": "",  # empty key (should be filtered)
            "canonical_name_en": "Unknown",
            "name_vi": "Không rõ",
            "category": "Khác",
            "source": "Unknown",
            "source_priority": "3",
            "source_id": "",
            "confidence_score": "0.0",
            "is_estimated": "true",
            "nang_luong_kcal": "0",
            "chat_dam_g": "0",
            "chat_beo_g": "0",
            "chat_bot_duong_g": "0",
            "vitamin_a_mcg": "0",
            "beta_carotene_mcg": "0",
            "vitamin_c_mg": "0",
            "calcium_mg": "0",
            "iron_mg": "0",
            "zinc_mg": "0",
            "sodium_mg": "0",
            "cholesterol_mg": "0",
            "magnesium_mg": "0",
            "transfat_mg": "0",
        },
    ]


@pytest.fixture
def sample_alias_rows() -> list[dict[str, str]]:
    """Provide sample alias rows for testing."""
    return [
        {
            "canonical_key": "beef",
            "alias_text": "thit bo",
            "alias_lang": "vi",
            "alias_type": "non_diacritic",
            "is_preferred": "false",
            "source": "NIN",
            "source_priority": "1",
        },
        {
            "canonical_key": "beef",
            "alias_text": "beef cuts",
            "alias_lang": "en",
            "alias_type": "synonym",
            "is_preferred": "false",
            "source": "Kaggle",
            "source_priority": "2",
        },
        {
            "canonical_key": "chicken",
            "alias_text": "ga",
            "alias_lang": "vi",
            "alias_type": "non_diacritic",
            "is_preferred": "false",
            "source": "NIN",
            "source_priority": "1",
        },
    ]


@pytest.fixture
def csv_path() -> Path:
    """Get path to test CSV file."""
    return ROOT_DIR / "data" / "raw" / "viendinhduong_nutrients.csv"


@pytest.fixture
def alias_csv_path() -> Path:
    """Get path to test alias CSV file."""
    return ROOT_DIR / "data" / "raw" / "food_aliases_vi.csv"


@pytest.fixture
def manifest_path() -> Path:
    """Get path to dataset version manifest."""
    return ROOT_DIR / "data" / "raw" / "dataset_version_manifest.json"


@pytest.fixture(autouse=True)
def log_test_start_end(request):
    """Log test start and end for debugging."""
    print(f"\n{'='*60}")
    print(f"TEST START: {request.node.name}")
    print(f"{'='*60}")
    yield
    print(f"{'='*60}")
    print(f"TEST END: {request.node.name}")
    print(f"{'='*60}\n")
