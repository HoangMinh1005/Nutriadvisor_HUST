"""Simple SQL migration runner for PostgreSQL.

Applies SQL files in lexical order from data/sql/init and tracks applied files
in schema_migrations using filename + sha256 checksum.

Usage:
    python data/scripts/run_migrations.py
    python data/scripts/run_migrations.py --migrations-dir data/sql/init
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
from urllib.parse import quote_plus

import psycopg
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = ROOT_DIR / "data" / "sql" / "init"

load_dotenv(ROOT_DIR / "backend" / ".env")
load_dotenv(ROOT_DIR / ".env")


def _database_url() -> str:
    """Read DATABASE_URL or build it from POSTGRES_* variables."""
    db_url = os.getenv("DATABASE_URL", "")
    if db_url:
        return db_url

    user = os.getenv("POSTGRES_USER", "")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db_name = os.getenv("POSTGRES_DB", "")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")

    if user and db_name:
        encoded_password = quote_plus(password)
        return f"postgresql://{user}:{encoded_password}@{host}:{port}/{db_name}"

    raise RuntimeError(
        "DATABASE_URL is not configured and POSTGRES_USER/POSTGRES_DB are missing"
    )


def _parse_args() -> argparse.Namespace:
    """Parse CLI arguments for migrations path and optional DB URL override."""
    parser = argparse.ArgumentParser(description="Apply SQL migrations to PostgreSQL")
    parser.add_argument(
        "--migrations-dir",
        default=str(DEFAULT_MIGRATIONS_DIR),
        help="Directory that contains .sql migration files",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Optional DATABASE_URL override (otherwise use environment variable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without applying SQL",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Record pending migrations as applied without executing SQL",
    )
    return parser.parse_args()


def _migration_checksum(sql_text: str) -> str:
    """Compute a deterministic sha256 checksum for migration content."""
    return hashlib.sha256(sql_text.encode("utf-8")).hexdigest()


def _ensure_migration_table(cur: psycopg.Cursor) -> None:
    """Create schema_migrations table if it does not exist."""
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_name TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def _discover_migrations(migrations_dir: Path) -> list[Path]:
    """Return lexically sorted SQL migration files from the target directory."""
    if not migrations_dir.exists():
        raise FileNotFoundError(f"Migrations directory not found: {migrations_dir}")
    files = sorted(path for path in migrations_dir.iterdir() if path.is_file() and path.suffix.lower() == ".sql")
    if not files:
        raise RuntimeError(f"No .sql migration files found in: {migrations_dir}")
    return files


def _get_applied_checksum(cur: psycopg.Cursor, migration_name: str) -> str | None:
    """Get stored checksum for a migration name, or None when not applied yet."""
    cur.execute(
        "SELECT checksum FROM schema_migrations WHERE migration_name = %s;",
        (migration_name,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return str(row[0])


def _record_applied(cur: psycopg.Cursor, migration_name: str, checksum: str) -> None:
    """Record a newly applied migration in schema_migrations."""
    cur.execute(
        """
        INSERT INTO schema_migrations (migration_name, checksum)
        VALUES (%s, %s);
        """,
        (migration_name, checksum),
    )


def run() -> None:
    """Apply pending migrations and validate checksum consistency for applied files."""
    args = _parse_args()
    migrations_dir = Path(args.migrations_dir).resolve()
    migrations = _discover_migrations(migrations_dir)

    applied_count = 0
    skipped_count = 0

    print(f"Migration directory: {migrations_dir}")
    print(f"Found {len(migrations)} migration file(s)")

    if args.dry_run:
        for migration_path in migrations:
            print(f"DRYRUN  {migration_path.name}")
        print("Migration run completed")
        print("Applied: 0")
        print(f"Skipped: {len(migrations)}")
        return

    database_url = args.database_url.strip() or _database_url()

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            _ensure_migration_table(cur)
        conn.commit()

        for migration_path in migrations:
            sql_text = migration_path.read_text(encoding="utf-8")
            checksum = _migration_checksum(sql_text)
            migration_name = migration_path.name

            with conn.cursor() as cur:
                applied_checksum = _get_applied_checksum(cur, migration_name)

                if applied_checksum is not None:
                    if applied_checksum != checksum:
                        raise RuntimeError(
                            "Checksum mismatch for already applied migration "
                            f"{migration_name}. Applied={applied_checksum}, Current={checksum}. "
                            "Create a new migration file instead of editing an applied one."
                        )
                    print(f"SKIP    {migration_name}")
                    skipped_count += 1
                    continue

                if args.baseline:
                    _record_applied(cur, migration_name, checksum)
                    conn.commit()
                    print(f"BASELINE {migration_name}")
                    applied_count += 1
                    continue

                try:
                    cur.execute(sql_text)
                    _record_applied(cur, migration_name, checksum)
                    conn.commit()
                    print(f"APPLIED {migration_name}")
                    applied_count += 1
                except Exception:
                    conn.rollback()
                    raise

    print("Migration run completed")
    print(f"Applied: {applied_count}")
    print(f"Skipped: {skipped_count}")


if __name__ == "__main__":
    run()
