"""Database connectivity and table structure verification module."""

import os
import sys
import time
from typing import List, Tuple

import psycopg2
from psycopg2 import sql


class DatabaseChecker:
    """Verify PostgreSQL connection and required table existence."""

    REQUIRED_TABLES = [
        "categories",
        "food_groups",
        "dataset_versions",
        "foods",
        "food_nutrients",
        "food_price_estimates",
        "food_aliases",
        "food_tags",
        "food_tag_mapping",
        "food_search_logs",
        "user_profiles",
        "meal_plans",
    ]

    def __init__(self, db_url: str | None = None) -> None:
        """Initialize database checker with connection URL."""
        self.db_url = db_url or os.getenv("DATABASE_URL", "")
        self.connection = None
        self.cursor = None

    def connect(self, max_retries: int = 10, retry_delay: int = 1) -> bool:
        """
        Establish connection to PostgreSQL with retry logic.

        Args:
            max_retries: Maximum number of connection attempts
            retry_delay: Delay in seconds between retries

        Returns:
            True if connection successful, False otherwise
        """
        if not self.db_url:
            print("❌ DATABASE_URL environment variable is not set.")
            return False

        for attempt in range(1, max_retries + 1):
            try:
                self.connection = psycopg2.connect(self.db_url)
                self.cursor = self.connection.cursor()
                print(f"✅ Connected to PostgreSQL (Attempt {attempt}/{max_retries})")
                return True
            except psycopg2.OperationalError as e:
                print(f"⏳ Connection attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    time.sleep(retry_delay)
                else:
                    print(f"❌ Failed to connect after {max_retries} attempts.")
                    return False

        return False

    def check_tables_exist(self) -> Tuple[bool, List[str]]:
        """
        Check if all required tables exist in the database.

        Returns:
            Tuple of (all_exist: bool, missing_tables: List[str])
        """
        if not self.cursor:
            print("❌ No database connection established.")
            return False, self.REQUIRED_TABLES

        missing_tables = []

        try:
            for table_name in self.REQUIRED_TABLES:
                self.cursor.execute(
                    sql.SQL(
                        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s"
                    ),
                    [table_name],
                )
                result = self.cursor.fetchone()

                if result:
                    print(f"  ✅ Table '{table_name}' exists")
                else:
                    print(f"  ❌ Table '{table_name}' MISSING")
                    missing_tables.append(table_name)

            return len(missing_tables) == 0, missing_tables

        except psycopg2.Error as e:
            print(f"❌ Error checking tables: {e}")
            return False, self.REQUIRED_TABLES

    def close(self) -> None:
        """Close database connection."""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
            print("Database connection closed.")


def verify_database() -> bool:
    """
    Main verification function to check database readiness.

    Returns:
        True if all checks pass, False otherwise
    """
    print("\n" + "=" * 60)
    print("DATABASE INITIALIZATION CHECK")
    print("=" * 60)

    checker = DatabaseChecker()

    # Step 1: Connect
    if not checker.connect():
        print("\n❌ Database connection FAILED. Exiting...")
        return False

    # Step 2: Check tables
    print("\nChecking required tables:")
    tables_ok, missing = checker.check_tables_exist()

    # Step 3: Report
    if tables_ok:
        print("\n" + "=" * 60)
        print("✅ ALL CHECKS PASSED - Database is ready!")
        print("=" * 60 + "\n")
    else:
        print("\n" + "=" * 60)
        print(f"❌ MISSING TABLES: {', '.join(missing)}")
        print("Please ensure SQL initialization scripts have run.")
        print("=" * 60 + "\n")

    checker.close()
    return tables_ok


if __name__ == "__main__":
    success = verify_database()
    sys.exit(0 if success else 1)
