import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query
from dotenv import load_dotenv

load_dotenv()

from .check_db import verify_database
from .services.food_search import search_foods as search_foods_index

app = FastAPI(title="Nutri-Advisor AI Backend")


def _get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return db_url


# Verify database on startup
print("\n[STARTUP] Initializing application...")
if not verify_database():
    print("\n⚠️  WARNING: Database verification failed. Some features may not work.")
    print("    Please check if PostgreSQL is running and SQL scripts have been executed.\n")


@app.get("/")
def root() -> Dict[str, str]:
    return {"message": "Nutri-Advisor backend is running"}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/foods/search")
def search_foods(
    q: str = Query(..., min_length=1, description="Food name keyword"),
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    try:
        return search_foods_index(query=q.strip(), limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Food search failed: {exc}")
