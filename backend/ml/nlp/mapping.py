"""Helpers to load and resolve food item mappings (name -> food_item_id).

This simple module uses a JSON mapping file and a fuzzy matcher fallback
using difflib.get_close_matches to resolve near matches.
"""
from __future__ import annotations

import json
from difflib import get_close_matches
from typing import Dict, Optional


def load_mapping(path: str) -> Dict[str, str]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # normalize keys to lower-case trimmed
    return {k.strip().lower(): v for k, v in data.items()}


def resolve_name(name: str, mapping: Dict[str, str], cutoff: float = 0.6) -> Optional[str]:
    if not name or not mapping:
        return None
    key = name.strip().lower()
    if key in mapping:
        return mapping[key]

    # fuzzy match against mapping keys
    keys = list(mapping.keys())
    matches = get_close_matches(key, keys, n=1, cutoff=cutoff)
    if matches:
        return mapping[matches[0]]
    return None
