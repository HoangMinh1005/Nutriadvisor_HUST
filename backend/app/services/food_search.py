from __future__ import annotations

import os
import re
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor


def _get_database_url() -> str:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not configured")
    return db_url


def _normalize_query(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _fetch_aliases_for_food(food_id: int) -> list[str]:
    query = """
        SELECT alias_text
        FROM food_aliases
        WHERE food_id = %s
        ORDER BY is_preferred DESC, alias_type ASC, alias_text ASC;
    """
    with psycopg2.connect(_get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (food_id,))
            return [row[0] for row in cur.fetchall()]


def _format_items(rows: list[dict[str, Any]], include_score: bool = False) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        item = {
            "food_id": row.get("food_id"),
            "canonical_key": row.get("canonical_key"),
            "canonical_name_en": row.get("canonical_name_en"),
            "name_vi": row.get("name_vi"),
            "category": row.get("food_group_name"),
            "source": row.get("source_name"),
            "source_priority": row.get("source_priority"),
            "calories": float(row.get("energy_kcal") or 0),
            "protein": float(row.get("protein_g") or 0),
            "fat": float(row.get("fat_g") or 0),
            "carbs": float(row.get("carbs_g") or 0),
            "alias_texts": _fetch_aliases_for_food(int(row["food_id"])),
        }
        if include_score:
            score_val = row.get("match_score")
            if score_val is None:
                score_val = 1.0
            item["match_score"] = round(float(score_val), 3)
        items.append(item)
    return items


def _search_exact(query: str, limit: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            f.food_id,
            f.canonical_key,
            f.canonical_name_en,
            f.name_vi,
            g.display_name AS food_group_name,
            f.source_name,
            f.source_priority,
            n.energy_kcal,
            n.protein_g,
            n.fat_g,
            n.carbs_g
        FROM food_aliases a
        JOIN foods f ON f.food_id = a.food_id
        JOIN food_groups g ON g.food_group_id = f.food_group_id
        JOIN food_nutrients n ON n.food_id = f.food_id
        WHERE LOWER(a.alias_text) = LOWER(%s)
           OR LOWER(f.canonical_key) = LOWER(%s)
           OR LOWER(f.canonical_name_en) = LOWER(%s)
           OR LOWER(COALESCE(f.name_vi, '')) = LOWER(%s)
        ORDER BY a.is_preferred DESC, f.source_priority ASC, f.food_id ASC
        LIMIT %s;
    """
    with psycopg2.connect(_get_database_url()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (query, query, query, query, limit))
            return list(cur.fetchall())


def _search_fuzzy(query: str, limit: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            f.food_id,
            f.canonical_key,
            f.canonical_name_en,
            f.name_vi,
            g.display_name AS food_group_name,
            f.source_name,
            f.source_priority,
            n.energy_kcal,
            n.protein_g,
            n.fat_g,
            n.carbs_g,
            similarity(a.alias_text, %s) AS match_score
        FROM food_aliases a
        JOIN foods f ON f.food_id = a.food_id
        JOIN food_groups g ON g.food_group_id = f.food_group_id
        JOIN food_nutrients n ON n.food_id = f.food_id
        WHERE similarity(a.alias_text, %s) >= 0.3
        ORDER BY match_score DESC, a.is_preferred DESC, f.source_priority ASC
        LIMIT %s;
    """
    with psycopg2.connect(_get_database_url()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (query, query, limit))
            return list(cur.fetchall())


def _search_fallback(query: str, limit: int) -> list[dict[str, Any]]:
    sql = """
        SELECT
            f.food_id,
            f.canonical_key,
            f.canonical_name_en,
            f.name_vi,
            g.display_name AS food_group_name,
            f.source_name,
            f.source_priority,
            n.energy_kcal,
            n.protein_g,
            n.fat_g,
            n.carbs_g,
            GREATEST(
                similarity(f.canonical_name_en, %s),
                similarity(COALESCE(f.name_vi, ''), %s)
            ) AS match_score
        FROM foods f
        JOIN food_groups g ON g.food_group_id = f.food_group_id
        JOIN food_nutrients n ON n.food_id = f.food_id
        ORDER BY match_score DESC, f.source_priority ASC, f.food_id ASC
        LIMIT %s;
    """
    with psycopg2.connect(_get_database_url()) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (query, query, limit))
            return list(cur.fetchall())


def _log_search(query_text: str, tier: str, rows: list[dict[str, Any]]) -> None:
    normalized = _normalize_query(query_text)
    matched_food_id = rows[0].get("food_id") if rows else None
    confidence = float(rows[0].get("match_score") or 0) if rows else 0.0

    sql = """
        INSERT INTO food_search_logs (
            query_text,
            normalized_query,
            matched_food_id,
            match_tier,
            confidence_score,
            user_locale,
            user_action
        ) VALUES (%s, %s, %s, %s, %s, 'vi', 'search');
    """
    with psycopg2.connect(_get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (query_text, normalized, matched_food_id, tier, confidence))
        conn.commit()


def search_foods(query: str, limit: int = 5) -> dict[str, Any]:
    query = query.strip()
    if not query:
        return {"query": query, "tier": "empty", "count": 0, "items": []}

    exact_rows = _search_exact(query, limit)
    if exact_rows:
        _log_search(query, "exact", exact_rows)
        return {
            "query": query,
            "tier": "exact",
            "count": len(exact_rows),
            "items": _format_items(exact_rows, include_score=True),
        }

    fuzzy_rows = _search_fuzzy(query, limit)
    if fuzzy_rows:
        _log_search(query, "fuzzy", fuzzy_rows)
        return {
            "query": query,
            "tier": "fuzzy",
            "count": len(fuzzy_rows),
            "items": _format_items(fuzzy_rows, include_score=True),
        }

    fallback_rows = _search_fallback(query, limit)
    _log_search(query, "fallback" if fallback_rows else "none", fallback_rows)
    return {
        "query": query,
        "tier": "fallback",
        "count": len(fallback_rows),
        "items": _format_items(fallback_rows, include_score=True),
    }
