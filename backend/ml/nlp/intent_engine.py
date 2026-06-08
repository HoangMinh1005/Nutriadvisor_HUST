"""Hybrid intent engine for NutriAdvisor.

Local path: TF-IDF + MultinomialNB + regex extraction.
Fallback path: Gemini API returning strict JSON.
"""

from __future__ import annotations

import json
import os
import pickle
import re
import threading
import urllib.error
import urllib.request
from dataclasses import asdict
import logging
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import psycopg
except ImportError:
    import psycopg2
    class Psycopg3ConnectionProxy:
        def __init__(self, conn):
            self._conn = conn
        def __getattr__(self, name):
            return getattr(self._conn, name)
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            try:
                if exc_type is not None:
                    self._conn.rollback()
                else:
                    self._conn.commit()
            finally:
                self._conn.close()
        def close(self):
            self._conn.close()
        def cursor(self, *args, **kwargs):
            return self._conn.cursor(*args, **kwargs)
    class psycopg:
        @staticmethod
        def connect(*args, **kwargs):
            return Psycopg3ConnectionProxy(psycopg2.connect(*args, **kwargs))
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from .cache import IntentCache
from .prompts import GEMINI_SYSTEM_PROMPT, VALID_INTENTS, build_user_prompt
from .schemas import NLPResult, TrainingExample

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
if os.path.exists("/models"):
    DEFAULT_MODEL_DIR = Path("/models") / "nlp"
else:
    DEFAULT_MODEL_DIR = WORKSPACE_ROOT / "models" / "nlp"
DEFAULT_DATA_PATH = Path(__file__).resolve().parent / "data" / "intent_examples.jsonl"
MODEL_ARTIFACT_NAME = "intent_engine.pkl"
PROMPT_VERSION = "v3"
SCHEMA_VERSION = "v3"
NEGATIVE_CACHE_TTL_SECONDS = 120
PRICE_TABLE_NAME = "food_price_estimates"

INTENT_TTLS_SECONDS = {
    "update_profile": 7 * 24 * 60 * 60,
    "ask_nutrition": 3 * 24 * 60 * 60,
    "recommend_meal": 12 * 60 * 60,
    "unknown": 15 * 60,
}

NUTRIENT_FIELD_ALIASES: dict[str, list[str]] = {
    "energy_kcal": ["energy_kcal", "kcal", "calories", "calo", "năng lượng", "nang luong", "energy"],
    "protein_g": ["protein_g", "protein", "đạm", "dam"],
    "fat_g": ["fat_g", "fat", "chất béo", "chat beo", "lipid"],
    "carbs_g": ["carbs_g", "carb", "carbs", "tinh bột", "tinh bot", "carbohydrate", "đường", "duong"],
    "vitamin_a_mcg": ["vitamin_a_mcg", "vitamin a", "vitamin a_", "vit a", "retinol"],
    "beta_carotene_mcg": ["beta_carotene_mcg", "beta carotene", "beta-carotene", "beta caroten", "beta-caroten", "carotene beta"],
    "vitamin_c_mg": ["vitamin_c_mg", "vitamin c"],
    "calcium_mg": ["calcium_mg", "calcium", "canxi"],
    "iron_mg": ["iron_mg", "iron", "sắt", "sat"],
    "zinc_mg": ["zinc_mg", "zinc", "kẽm", "kem"],
    "sodium_mg": ["sodium_mg", "sodium", "natri", "muối", "muoi"],
    "cholesterol_mg": ["cholesterol_mg", "cholesterol"],
    "magnesium_mg": ["magnesium_mg", "magnesium", "magie"],
    "transfat_mg": ["transfat_mg", "trans fat", "transfat", "fat trans", "chất béo trans", "chat beo trans"],
}


class IntentEngine:
    """Predict user intent and extract structured entities."""

    def __init__(
        self,
        model_dir: str | Path = DEFAULT_MODEL_DIR,
        cache: IntentCache | None = None,
        gemini_api_key: str | None = None,
        gemini_model: str | None = None,
        confidence_threshold: float | None = None,
        require_gemini: bool | None = None,
        food_mapping: dict[str, str] | str | None = None,
    ) -> None:
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "") if gemini_api_key is None else gemini_api_key
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") if gemini_model is None else gemini_model
        fallback_models_env = os.getenv("GEMINI_MODEL_FALLBACKS", "gemini-3.1-flash-lite")
        self.gemini_model_fallbacks = [
            model.strip() for model in fallback_models_env.split(",") if model.strip() and model.strip() != self.gemini_model
        ]
        cache_namespace = f"nlp:intent:{SCHEMA_VERSION}:{PROMPT_VERSION}:{self.gemini_model}"
        self.cache = cache or IntentCache(redis_url=os.getenv("NLP_CACHE_URL"), namespace=cache_namespace)
        env_threshold = os.getenv("NLP_CONFIDENCE_THRESHOLD")
        if confidence_threshold is None:
            try:
                confidence_threshold = float(env_threshold) if env_threshold is not None else 0.7
            except ValueError:
                confidence_threshold = 0.7
        self.confidence_threshold = float(confidence_threshold)
        if require_gemini is None:
            env_req = os.getenv("NLP_REQUIRE_GEMINI")
            require_gemini = bool(str(env_req).strip().lower() in {"1", "true", "yes"}) if env_req is not None else False
        self.require_gemini = bool(require_gemini)

        self.vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), lowercase=True)
        self.classifier = MultinomialNB()
        self.is_trained = False
        self._lock_registry: dict[str, threading.Lock] = {}
        self._lock_registry_guard = threading.Lock()
        self._last_gemini_error_code: int | None = None

        # Load food mapping if provided. Accept either a dict or a path to JSON file.
        self.food_mapping: dict[str, str] | None = None
        if isinstance(food_mapping, str):
            try:
                from .mapping import load_mapping

                self.food_mapping = load_mapping(food_mapping)
            except Exception:
                self.food_mapping = None
        elif isinstance(food_mapping, dict):
            # normalize keys
            self.food_mapping = {k.strip().lower(): v for k, v in food_mapping.items()}

        self.price_defaults = self._load_price_defaults_from_db()

    def train(self, examples: Sequence[TrainingExample | dict[str, Any] | tuple[str, str]]) -> dict[str, Any]:
        texts: list[str] = []
        labels: list[str] = []

        for example in examples:
            text, intent = self._coerce_example(example)
            texts.append(text)
            labels.append(intent)

        if not texts:
            raise ValueError("No training examples provided")

        matrix = self.vectorizer.fit_transform(texts)
        self.classifier.fit(matrix, labels)
        self.is_trained = True
        self._save_artifacts()

        return {
            "samples": len(texts),
            "classes": sorted(set(labels)),
            "artifact": str(self.model_dir / MODEL_ARTIFACT_NAME),
        }

    def predict(self, user_query: str) -> NLPResult:
        query = (user_query or "").strip()
        if not query:
            result = NLPResult(intent="unknown", confidence=0.0, entities=self._default_entities(), source="local")
            # normalize cache key
            cache_key = query.lower()
            # Store cached payload with provenance
            payload = result.to_dict()
            payload["cached_from"] = payload.get("source")
            payload["source"] = "cache"
            self.cache.set_with_ttl(cache_key, payload, self._cache_ttl_for_intent(result.intent))
            return result

        # normalize cache key to avoid accidental cache misses due to case/spacing
        cache_key = query.lower()
        cached = self.cache.get(cache_key)
        if cached:
            logging.getLogger(__name__).debug("Cache hit for query '%s' (mode=%s)", query, self.cache.mode)
            return self._result_from_payload(cached)

        logging.getLogger(__name__).debug("Cache miss for query '%s' (mode=%s)", query, self.cache.mode)

        query_lock = self._get_query_lock(cache_key)
        with query_lock:
            cached_after_wait = self.cache.get(cache_key)
            if cached_after_wait:
                logging.getLogger(__name__).debug("Cache hit after wait for query '%s' (mode=%s)", query, self.cache.mode)
                return self._result_from_payload(cached_after_wait)

            self.ensure_ready()
            local_result = self._predict_local(query)

            if local_result.confidence >= self.confidence_threshold:
                # High-confidence local prediction: cache and return immediately
                ttl_seconds = self._cache_ttl_for_intent(local_result.intent)
                payload = local_result.to_dict()
                payload["cached_from"] = payload.get("source")
                payload["source"] = "cache"
                self.cache.set_with_ttl(cache_key, payload, ttl_seconds)
                logging.getLogger(__name__).debug(
                    "Cached local result for query '%s' with ttl=%ss (intent=%s, mode=%s)",
                    query,
                    ttl_seconds,
                    local_result.intent,
                    self.cache.mode,
                )
                return local_result

            negative_cache_key = f"{cache_key}::gemini_429"
            negative_cache = self.cache.get(negative_cache_key)
            if negative_cache:
                logging.getLogger(__name__).debug(
                    "Negative cache hit for query '%s' (mode=%s); skipping Gemini", query, self.cache.mode
                )
                if self.require_gemini:
                    return NLPResult(intent="unknown", confidence=0.0, entities=self._default_entities(), source="local", raw_response="gemini_rate_limited")
                return local_result

            # Low-confidence local prediction: always attempt Gemini fallback
            logging.getLogger(__name__).debug(
                "Local confidence %.3f below threshold %.3f — calling Gemini for '%s'",
                local_result.confidence,
                self.confidence_threshold,
                query,
            )
            gemini_result = self._predict_via_gemini(query)
            if gemini_result:
                # Gemini succeeded: cache and return Gemini result
                ttl_seconds = self._cache_ttl_for_intent(gemini_result.intent)
                payload = gemini_result.to_dict()
                payload["cached_from"] = payload.get("source")
                payload["source"] = "cache"
                self.cache.set_with_ttl(cache_key, payload, ttl_seconds)
                logging.getLogger(__name__).debug(
                    "Cached Gemini result for query '%s' with ttl=%ss (intent=%s, mode=%s)",
                    query,
                    ttl_seconds,
                    gemini_result.intent,
                    self.cache.mode,
                )
                return gemini_result

            # Gemini unavailable or failed. Cache 429 briefly to avoid repeated hits.
            if self._last_gemini_error_code == 429:
                self.cache.set_with_ttl(
                    negative_cache_key,
                    {"error": "gemini_rate_limited", "query": query},
                    NEGATIVE_CACHE_TTL_SECONDS,
                )
                logging.getLogger(__name__).warning(
                    "Cached negative Gemini rate-limit for query '%s' ttl=%ss (mode=%s)",
                    query,
                    NEGATIVE_CACHE_TTL_SECONDS,
                    self.cache.mode,
                )

            if self.require_gemini:
                # When Gemini is required, return an explicit unknown result so the
                # caller does not mistakenly act on a low-confidence local prediction.
                return NLPResult(intent="unknown", confidence=0.0, entities=self._default_entities(), source="local", raw_response="gemini_unavailable")

            return local_result

    def ensure_ready(self) -> None:
        if self.is_trained:
            return

        if self._load_artifacts():
            return

        examples = load_default_training_examples()
        if not examples:
            raise RuntimeError("No training examples available for NLP engine")

        self.train(examples)

    def extract_entities(self, user_query: str) -> dict[str, Any]:
        query = user_query.lower()
        entities = self._default_entities()

        budget_value = self._parse_budget_vnd(query)
        if budget_value is not None:
            entities["budget_vnd"] = budget_value
            entities["query_keyword"] = "budget_conscious"

        calories_match = re.search(r"(\d{3,4})\s*(kcal|calo|cal)\b", query)
        if calories_match:
            entities["calories"] = int(calories_match.group(1))
            entities["profile_updates"]["daily_calorie_target"] = int(calories_match.group(1))

        weight_match = re.search(r"(giảm|giam|tang|tăng)\s*(\d+(?:[\.,]\d+)?)\s*(?:kg|cân|can|ky|kí)?\b", query)
        if weight_match:
            weight_value = float(weight_match.group(2).replace(",", "."))
            direction = weight_match.group(1)
            if direction in {"giảm", "giam"}:
                entities["weight_change_kg"] = -abs(weight_value)
                entities["health_goal"] = "weight_loss"
            else:
                entities["weight_change_kg"] = abs(weight_value)
                entities["health_goal"] = "muscle_gain"

        if entities["health_goal"] == "unknown" and any(
            keyword in query for keyword in ["tang co", "tăng cơ", "xay co", "muscle", "gym", "tap gym", "tập gym"]
        ):
            entities["health_goal"] = "muscle_gain"
        elif entities["health_goal"] == "unknown" and any(
            keyword in query for keyword in ["giam can", "giảm cân", "giam mo", "giảm mỡ"]
        ):
            entities["health_goal"] = "weight_loss"
        elif entities["health_goal"] == "unknown" and any(
            keyword in query for keyword in ["giu can", "duy tri", "maintain", "maintenance"]
        ):
            entities["health_goal"] = "maintenance"

        duration_days = self._parse_duration_days(query)
        if duration_days is not None:
            entities["duration_days"] = duration_days

        nutrients = self._parse_nutrients(query)
        if nutrients:
            entities["nutrients"] = nutrients

        food_items = self._parse_food_items(query)
        if food_items:
            entities["food_items"] = food_items

        query_keyword = self._classify_query_keyword(query, nutrients, budget_value)
        if query_keyword is not None:
            entities["query_keyword"] = query_keyword

        replacement_target = self._parse_replacement_target(query)
        if replacement_target is not None:
            entities["replacement_target"] = replacement_target
            entities["query_keyword"] = "thay thế"

        profile_updates = self._parse_profile_updates(query)
        if any(value is not None for value in profile_updates.values()):
            if profile_updates["daily_calorie_target"] is None and entities["calories"] is not None:
                profile_updates["daily_calorie_target"] = int(entities["calories"])
            entities["profile_updates"] = profile_updates

        allergies = self._parse_allergies(query)
        entities["allergies"] = sorted(set(allergies))

        dietary_keywords = {
            "vegetarian": ["vegetarian", "chay"],
            "vegan": ["vegan"],
            "halal": ["halal"],
        }
        dietary_restrictions: list[str] = []
        for label, keywords in dietary_keywords.items():
            if any(keyword in query for keyword in keywords):
                dietary_restrictions.append(label)
        entities["dietary_restrictions"] = dietary_restrictions

        if entities["query_keyword"] is None and self._is_budget_conscious_text(query):
            entities["query_keyword"] = "budget_conscious"

        if entities["profile_updates"]["weight_goal"] is None and entities["health_goal"] != "unknown":
            entities["profile_updates"]["weight_goal"] = entities["health_goal"]

        return entities

    def _is_nutrition_query(self, query: str) -> bool:
        nutrient_terms = [alias for aliases in NUTRIENT_FIELD_ALIASES.values() for alias in aliases]
        food_query_cues = ["bao nhiêu", "bao nhieu", "lượng", "luong", "trong", "chứa", "chua", "có bao nhiêu", "co bao nhieu", "hàm lượng", "ham luong"]
        return any(term in query for term in nutrient_terms) and any(cue in query for cue in food_query_cues)

    def _is_replacement_query(self, query: str) -> bool:
        replacement_cues = ["thay", "thay thế", "thay the", "đổi", "doi", "replace", "substitute"]
        return any(cue in query for cue in replacement_cues)

    def _classify_query_keyword(self, query: str, nutrients: list[str], budget_value: int | None = None) -> str | None:
        if budget_value is not None:
            return "budget_conscious"

        if self._is_nutrition_query(query):
            return "bao nhiêu"

        if self._is_replacement_query(query):
            return "thay thế"

        if nutrients:
            low_cues = ["thấp", "thap", "ít", "it", "low", "giảm", "giam", "hạn chế", "han che"]
            rich_cues = ["giàu", "giau", "nhiều", "nhieu", "tăng", "tang", "protein", "chất xơ", "chat xơ", "xơ"]

            if any(cue in query for cue in low_cues):
                return "thấp"
            if any(cue in query for cue in rich_cues):
                return "giàu"

        return None

    def _is_budget_conscious_text(self, query: str) -> bool:
        budget_signals = [
            "tiết kiệm",
            "tiet kiem",
            "rẻ",
            "re",
            "giá rẻ",
            "gia re",
            "bình dân",
            "binh dan",
            "kinh phí",
            "kinh phi",
            "ngân sách",
            "ngan sach",
            "budget",
        ]
        return any(signal in query for signal in budget_signals)

    def _parse_profile_updates(self, query: str) -> dict[str, Any]:
        profile_updates = self._default_profile_updates()

        gender_match = re.search(r"\b(nam|nu|nữ|male|female|other)\b", query)
        if gender_match:
            token = gender_match.group(1)
            if token in {"nam", "male"}:
                profile_updates["gender"] = "male"
            elif token in {"nu", "nữ", "female"}:
                profile_updates["gender"] = "female"
            else:
                profile_updates["gender"] = "other"

        birth_year_match = re.search(r"sinh\s*(?:nam|năm)\s*(\d{4})\b", query)
        if birth_year_match:
            profile_updates["birth_year"] = int(birth_year_match.group(1))

        height_match = re.search(r"(?:cao|height)\s*(\d{2,3}(?:[\.,]\d+)?)\s*(?:cm|m)\b", query)
        if height_match:
            height_value = float(height_match.group(1).replace(",", "."))
            if "m" in height_match.group(0) and "cm" not in height_match.group(0) and height_value < 3:
                height_value *= 100
            profile_updates["height_cm"] = round(height_value, 2)

        # Accept compact forms like '1m8' or '1m80' (no spaces)
        if profile_updates["height_cm"] is None:
            m_concat = re.search(r"\b(\d)m(\d{1,2})\b", query)
            if m_concat:
                meters = int(m_concat.group(1))
                dec = m_concat.group(2)
                if len(dec) == 1:
                    cm = meters * 100 + int(dec) * 10
                else:
                    cm = meters * 100 + int(dec)
                profile_updates["height_cm"] = float(cm)

        # Accept '1.8m' or '1,8 m' forms
        if profile_updates["height_cm"] is None:
            m_decimal = re.search(r"\b(\d(?:[\.,]\d+))\s*m\b", query)
            if m_decimal:
                val = float(m_decimal.group(1).replace(",", "."))
                if val < 3:
                    profile_updates["height_cm"] = round(val * 100, 2)

        weight_match = re.search(r"(?:nang|nặng|can\s*nang|cân\s*nặng|weight)\s*(\d{2,3}(?:[\.,]\d+)?)\s*kg\b", query)
        if weight_match:
            profile_updates["weight_kg"] = float(weight_match.group(1).replace(",", "."))

        # Also accept short forms like "Tôi đang 70kg" as profile weight if no weight-change phrasing
        if profile_updates["weight_kg"] is None:
            short_weight = re.search(r"\b(?:tôi\s*(?:đang|hiện đang)?\s*)?(\d{2,3}(?:[\.,]\d+)?)\s*kg\b", query)
            if short_weight and not re.search(r"(?:giảm|giam|tăng|tang)\s*\d", query):
                profile_updates["weight_kg"] = float(short_weight.group(1).replace(",", "."))

        calories_match = re.search(r"(\d{3,4})\s*(?:kcal|calo|cal)\b", query)
        if calories_match:
            profile_updates["daily_calorie_target"] = int(calories_match.group(1))

        return profile_updates

    def _parse_nutrients(self, query: str) -> list[str]:
        nutrients: list[str] = []
        for nutrient, keywords in NUTRIENT_FIELD_ALIASES.items():
            if any(keyword in query for keyword in keywords):
                nutrients.append(nutrient)
        return list(dict.fromkeys(nutrients))

    def _parse_food_items(self, query: str) -> list[str]:
        food_patterns = [
            r"\bthịt bò\b",
            r"\bthit bo\b",
            r"\bthịt gà\b",
            r"\bthit ga\b",
            r"\bức gà\b",
            r"\buc ga\b",
            r"\bthịt heo\b",
            r"\bthit heo\b",
            r"\bcơm trắng\b",
            r"\bcom trang\b",
            r"\btrứng\b",
            r"\btrung\b",
            r"\bsữa\b",
            r"\bsua\b",
            r"\bcá\b",
            r"\bca\b",
            r"\bhải sản\b",
            r"\bhai san\b",
            r"\byến mạch\b",
            r"\byen mach\b",
        ]
        matches: list[str] = []
        for pattern in food_patterns:
            if re.search(pattern, query):
                token = pattern.replace(r"\b", "").strip("\\")
                matches.append(token)
        return list(dict.fromkeys(matches))

    def _parse_replacement_target(self, query: str) -> dict[str, Any]:
        if not self._is_replacement_query(query):
            return None

        # Detect explicit "replace X with Y" patterns only.
        replacement_pattern = re.search(
            r"(?:thay(?:\s+the)?|doi|đổi)\s+([\w\sàáảãạăắằẳẵặâấầẩẫậđêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]+?)\s+(?:bang|bằng|voi|với)",
            query,
        )
        if replacement_pattern:
            return replacement_pattern.group(1).strip()
        return None

    def _parse_budget_vnd(self, query: str) -> int | None:
        budget_cues = r"(?:kinh phí|kinh phi|ngân sách|ngan sach|chi phí|chi phi|budget|giá|gia|tầm|tam|khoảng|khoang)"
        suffix_pattern = r"(?:k|nghin|nghn|ngan|ngàn|nghìn)"

        cue_match = re.search(
            rf"{budget_cues}\s*(?:là|la|khoảng|khoang|tầm|tam|chừng|chung)?\s*(\d{{2,6}}(?:[\.,]\d+)?)\s*({suffix_pattern})?\b",
            query,
        )
        if cue_match:
            return self._normalize_budget_amount(cue_match.group(1), cue_match.group(2))

        suffix_match = re.search(
            rf"(?<!\d)(\d{{2,6}}(?:[\.,]\d+)?)\s*({suffix_pattern})\b",
            query,
        )
        if suffix_match:
            return self._normalize_budget_amount(suffix_match.group(1), suffix_match.group(2))

        plain_budget_match = re.search(
            rf"{budget_cues}\s*(?:là|la|khoảng|khoang|tầm|tam|chừng|chung)?\s*(\d{{3,6}}(?:[\.,]\d+)?)\b",
            query,
        )
        if plain_budget_match:
            return self._normalize_budget_amount(plain_budget_match.group(1), None)

        return None

    def _normalize_budget_amount(self, amount_text: str, suffix: str | None) -> int:
        amount = float(amount_text.replace(",", "."))
        suffix = (suffix or "").lower()
        if suffix in {"k", "nghin", "nghn", "ngan", "ngàn", "nghìn"} or amount < 1000:
            return int(amount * 1000)
        return int(amount)

    def _parse_allergies(self, query: str) -> list[str]:
        allergy_patterns = [
            r"\bhai san\b",
            r"\bhải sản\b",
            r"\btom\b",
            r"\btôm\b",
            r"\bcua\b",
            r"\bca\b",
            r"\bcá\b",
            r"\bdau phong\b",
            r"\bđậu phộng\b",
            r"\blac\b",
            r"\blạc\b",
            r"\bsua\b",
            r"\bsữa\b",
            r"\btrung\b",
            r"\btrứng\b",
            r"\bgluten\b",
        ]

        matches: list[str] = []
        for pattern in allergy_patterns:
            if re.search(pattern, query):
                token = pattern.replace(r"\b", "").strip("\\")
                matches.append(token)
        return matches

    def _parse_duration_days(self, query: str) -> int | None:
        day_map = {
            "ngay": 1, "ngày": 1,
            "tuan": 7, "tuần": 7,
            "thang": 30, "tháng": 30,
            "nam": 365, "năm": 365,
        }
        number_map = {
            "mot": 1, "một": 1, "hai": 2, "ba": 3, "bon": 4, "bốn": 4,
            "nam": 5, "năm": 5, "sau": 6, "sáu": 6, "bay": 7, "bảy": 7,
            "tam": 8, "tám": 8, "chin": 9, "chín": 9, "muoi": 10, "mười": 10
        }

        duration_match = re.search(
            r"(?P<value>\d+|mot|một|hai|ba|bon|bốn|nam|năm|sau|sáu|bay|bảy|tam|tám|chin|chín|muoi|mười)\s*(?P<unit>ngay|ngày|tuan|tuần|thang|tháng|nam|năm)\b",
            query,
        )
        if not duration_match:
            return None

        value_token = duration_match.group("value")
        unit_token = duration_match.group("unit")

        if value_token.isdigit():
            amount = int(value_token)
        else:
            amount = number_map.get(value_token, 1)

        return amount * day_map.get(unit_token, 1)

    def _parse_signed_weight_change(self, query: str) -> float | None:
        weight_match = re.search(
            r"(?P<direction>giảm|giam|tăng|tang)\s*(?P<value>\d+(?:[\.,]\d+)?)\s*(?:kg|cân|can|ky|kí)?\b",
            query,
        )
        if not weight_match:
            return None

        weight_value = float(weight_match.group("value").replace(",", "."))
        if weight_match.group("direction") in {"giảm", "giam"}:
            return -abs(weight_value)
        return abs(weight_value)

    def _predict_local(self, user_query: str) -> NLPResult:
        matrix = self.vectorizer.transform([user_query])
        label = str(self.classifier.predict(matrix)[0])
        confidence = float(self.classifier.predict_proba(matrix).max())
        entities = self.extract_entities(user_query)
        # If classifier predicts update_profile keep it; otherwise, if the
        # utterance looks like a profile statement (e.g., "Tôi đang 70kg")
        # and does not ask for recommendations, prefer `update_profile`.
        if label == "update_profile" and entities["health_goal"] == "unknown":
            entities["health_goal"] = "maintenance"

        if label != "update_profile" and self._is_profile_update_statement(user_query, entities):
            label = "update_profile"

        # If user expresses an explicit weight change (giảm/tăng) and does not
        # ask for recommendations, treat it as an update_profile intent.
        if label != "update_profile" and entities.get("weight_change_kg") is not None:
            if not any(cue in user_query.lower() for cue in ["gợi ý", "goi y", "thực đơn", "thuc don", "gợi ý thực phẩm"]):
                label = "update_profile"

        if self._is_nutrition_query(user_query.lower()) or entities.get("query_keyword") == "bao nhiêu":
            label = "ask_nutrition"

        return NLPResult(intent=label, confidence=confidence, entities=entities, source="local")

    def _predict_via_gemini(self, user_query: str) -> NLPResult | None:
        if not self.gemini_api_key:
            logging.getLogger(__name__).warning("GEMINI_API_KEY not set; skipping Gemini fallback for query: %s", user_query)
            self._last_gemini_error_code = None
            return None

        candidate_models = [self.gemini_model, *self.gemini_model_fallbacks]
        last_error: str | None = None
        self._last_gemini_error_code = None

        for model_name in candidate_models:
            result = self._predict_via_gemini_with_model(user_query, model_name)
            if result is not None:
                self._last_gemini_error_code = None
                return result
            last_error = model_name

        if last_error:
            logging.getLogger(__name__).warning("All Gemini models failed for query '%s'; last attempted model: %s", user_query, last_error)
        return None

    def _predict_via_gemini_with_model(self, user_query: str, model_name: str) -> NLPResult | None:
        logger = logging.getLogger(__name__)

        payload = {
            "systemInstruction": {"parts": [{"text": GEMINI_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": build_user_prompt(user_query)}]}],
            "generationConfig": {
                "temperature": 0,
                "topP": 1,
                "responseMimeType": "application/json",
            },
        }

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_name}:generateContent?key={self.gemini_api_key}"
        )

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            self._last_gemini_error_code = exc.code
            logger.warning("Gemini model %s failed with HTTP %s for query '%s'", model_name, exc.code, user_query)
            return None
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            self._last_gemini_error_code = None
            logger.exception("Gemini request failed for model %s and query '%s': %s", model_name, user_query, exc)
            return None

        try:
            data = json.loads(body)
            candidate_text = self._extract_candidate_text(data)
            parsed = self._parse_json_payload(candidate_text)
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            logger.exception("Failed to parse Gemini response for model %s and query '%s': %s", model_name, user_query, exc)
            return None

        if not parsed:
            self._last_gemini_error_code = None
            logger.warning("Gemini model %s returned empty/invalid payload for query: %s", model_name, user_query)
            return None

        return self._normalize_result(parsed, source="gemini", raw_response=candidate_text)

    def _extract_candidate_text(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates", [])
        if not candidates:
            raise KeyError("No Gemini candidates returned")

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        return "\n".join(texts).strip()

    def _parse_json_payload(self, text: str) -> dict[str, Any] | None:
        stripped = text.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.I | re.S).strip()

        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", stripped, flags=re.S)
            if not match:
                return None
            return json.loads(match.group(0))

    def _normalize_result(self, payload: dict[str, Any], source: str, raw_response: str | None = None) -> NLPResult:
        intent = str(payload.get("intent", "unknown"))
        if intent not in VALID_INTENTS:
            intent = "unknown"

        confidence_value = payload.get("confidence", 0.0)
        try:
            confidence = float(confidence_value)
        except (TypeError, ValueError):
            confidence = 0.0

        entities = payload.get("entities") or self._default_entities()
        if not isinstance(entities, dict):
            entities = self._default_entities()

        normalized = self._default_entities()
        normalized.update(entities)
        normalized["allergies"] = list(dict.fromkeys(normalized.get("allergies", [])))
        normalized["dietary_restrictions"] = list(dict.fromkeys(normalized.get("dietary_restrictions", [])))
        normalized["query_keyword"] = self._normalize_query_keyword(normalized.get("query_keyword"))

        food_items = normalized.get("food_items")
        if not isinstance(food_items, list):
            food_items = []
        normalized["food_items"] = list(dict.fromkeys(str(value) for value in food_items if value))

        nutrients = normalized.get("nutrients")
        if not isinstance(nutrients, list):
            nutrients = []
        normalized["nutrients"] = list(dict.fromkeys(str(value) for value in nutrients if value))

        profile_updates = normalized.get("profile_updates")
        if not isinstance(profile_updates, dict):
            profile_updates = self._default_profile_updates()
        normalized_profile_updates = self._default_profile_updates()
        normalized_profile_updates.update(profile_updates)
        normalized["profile_updates"] = normalized_profile_updates

        replacement_target = normalized.get("replacement_target")
        if isinstance(replacement_target, dict):
            replacement_target = replacement_target.get("food_name") or None
        elif replacement_target is not None:
            replacement_target = str(replacement_target).strip() or None
        normalized["replacement_target"] = replacement_target

        return NLPResult(
            intent=intent,
            confidence=confidence,
            entities=normalized,
            source=source,
            raw_response=raw_response,
        )

    def _get_query_lock(self, cache_key: str) -> threading.Lock:
        with self._lock_registry_guard:
            lock = self._lock_registry.get(cache_key)
            if lock is None:
                lock = threading.Lock()
                self._lock_registry[cache_key] = lock
            return lock

    def _cache_ttl_for_intent(self, intent: str) -> int:
        return INTENT_TTLS_SECONDS.get(intent, 24 * 60 * 60)

    def _normalize_query_keyword(self, value: Any) -> str | None:
        allowed_keywords = {"budget_conscious", "giàu", "thấp", "bao nhiêu", "thay thế"}
        if not isinstance(value, str):
            return None

        normalized_value = value.strip().lower()
        if normalized_value in allowed_keywords:
            return normalized_value
        return None

    def _result_from_payload(self, payload: dict[str, Any]) -> NLPResult:
        return self._normalize_result(payload, source=str(payload.get("source", "cache")), raw_response=payload.get("raw_response"))

    def _default_entities(self) -> dict[str, Any]:
        return {
            "budget_vnd": None,
            "query_keyword": None,
            "calories": None,
            "health_goal": "unknown",
            "allergies": [],
            "dietary_restrictions": [],
            "weight_change_kg": None,
            "duration_days": None,
            "food_items": [],
            "nutrients": [],
            "profile_updates": self._default_profile_updates(),
            "replacement_target": None,
        }

    def _default_profile_updates(self) -> dict[str, Any]:
        return {
            "full_name": None,
            "gender": None,
            "birth_year": None,
            "height_cm": None,
            "weight_kg": None,
            "weight_goal": None,
            "daily_calorie_target": None,
        }

    def _default_replacement_target(self) -> dict[str, Any]:
        return {
            "food_name": None,
            "nutrients": [],
        }

    def _get_database_url(self) -> str:
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            raise RuntimeError("DATABASE_URL is not configured")
        return db_url

    def _load_price_defaults_from_db(self) -> dict[str, Any] | None:
        """Load seeded price estimates directly from PostgreSQL."""
        query = f"""
            SELECT
                f.canonical_key,
                f.name_vi,
                COALESCE(p.price_100g_vnd, 0) AS price_100g,
                COALESCE(p.price_category, 'khong_xac_dinh') AS category,
                COALESCE(p.source_key, f.canonical_key) AS source_key,
                COALESCE(p.price_source, 'db') AS price_source,
                COALESCE(p.model_name, '') AS model_name,
                COALESCE(p.estimate_version, '') AS estimate_version,
                COALESCE(p.confidence_score, 0.700) AS confidence_score
            FROM {PRICE_TABLE_NAME} p
            JOIN foods f ON f.food_id = p.food_id
            WHERE f.is_active = TRUE
            ORDER BY f.food_id;
        """

        try:
            with psycopg.connect(self._get_database_url()) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    rows = cur.fetchall()
        except Exception as exc:
            logging.getLogger(__name__).warning("Could not load price estimates from DB: %s", exc)
            return None

        items: list[dict[str, Any]] = []
        by_canonical_key: dict[str, dict[str, Any]] = {}
        by_name_vi: dict[str, dict[str, Any]] = {}
        by_source_id: dict[str, dict[str, Any]] = {}

        for row in rows:
            canonical_key, name_vi, price_100g, category, source_key, price_source, model_name, estimate_version, confidence_score = row
            item = {
                "canonical_key": canonical_key,
                "name_vi": name_vi,
                "price_100g": int(price_100g or 0),
                "category": category,
                "source_key": source_key,
                "price_source": price_source,
                "model_name": model_name,
                "estimate_version": estimate_version,
                "confidence_score": float(confidence_score or 0.0),
            }
            items.append(item)
            by_canonical_key[canonical_key] = {"price_100g": item["price_100g"], "category": category}
            if name_vi:
                by_name_vi[name_vi] = {"price_100g": item["price_100g"], "category": category}
            by_source_id[source_key] = {"price_100g": item["price_100g"], "category": category}

        global_average = 15000
        if items:
            category_totals: dict[str, list[int]] = {}
            for item in items:
                category_totals.setdefault(item["category"], []).append(int(item["price_100g"]))
            category_averages = {cat: int(sum(values) / len(values)) for cat, values in category_totals.items() if values}
            if category_averages:
                global_average = int(sum(category_averages.values()) / len(category_averages))
        else:
            category_averages = {}

        return {
            "schema_version": 2,
            "summary": {
                "source": "postgresql",
                "total_items": len(items),
                "global_average_100g": global_average,
                "category_count": len(category_averages),
            },
            "items": items,
            "indices": {
                "by_canonical_key": by_canonical_key,
                "by_name_vi": by_name_vi,
                "by_source_id": by_source_id,
            },
            "global_average_100g": global_average,
            "categories": category_averages,
        }

    def _has_in_scope_keywords(self, query: str) -> bool:
        q = query.lower()
        keywords = [
            "thực đơn", "thuc don", "món", "mon", "ăn", "an", "uống", "uong",
            "calo", "kcal", "protein", "đạm", "dam", "béo", "beo", "lipid", "lipit",
            "carb", "tinh bột", "tinh bot", "chất xơ", "chat xo", "dinh dưỡng", "dinh duong",
            "dị ứng", "di ung", "thực phẩm", "thuc pham", "thay thế", "thay the", "thay", "đổi", "doi",
            "ức gà", "uc ga", "bò", "bo", "heo", "gà", "ga", "cá", "ca", "trứng", "trung",
            "sữa", "sua", "rau", "yến mạch", "yen mach", "hải sản", "hai san",
            "tăng", "tang", "giảm", "giam", "cân", "can", "kg", "bmi", "gym", "tập", "tap",
            "cơ", "co", "mỡ", "mo", "duy trì", "duy tri", "vnd", "ngàn", "ngan", "nghìn", "nghin",
            "giá", "gia", "tiền", "tien", "budget", "chi phí", "chi phi", "kinh phí", "kinh phi",
            "rẻ", "re", "đắt", "dat"
        ]
        return any(kw in q for kw in keywords)

    def predict_chat_intent(self, user_query: str) -> dict[str, Any]:
        """Predict user intent for chat interface, enforcing intent guardrails (Format 2)."""
        nlp_result = self.predict(user_query)
        intent = nlp_result.intent
        entities = nlp_result.entities or {}

        # Check if the query contains any in-scope keywords. If not, reject immediately.
        if not self._has_in_scope_keywords(user_query):
            chat_intent = "OUT_OF_SCOPE"
        else:
            # Check if it is a replacement query (FIND_ALTERNATIVE)
            is_replacement = (
                entities.get("replacement_target") is not None or 
                entities.get("query_keyword") == "thay thế" or
                (intent == "unknown" and self._is_replacement_query(user_query.lower()))
            )

            # Determine the matched chat domain
            if is_replacement:
                chat_intent = "FIND_ALTERNATIVE"
            elif intent == "recommend_meal":
                chat_intent = "SUGGEST_MEAL"
            elif intent == "ask_nutrition":
                chat_intent = "QUERY_NUTRITION"
            else:
                chat_intent = "OUT_OF_SCOPE"

        if chat_intent == "OUT_OF_SCOPE":
            return {
                "status": "rejected",
                "intent": "OUT_OF_SCOPE",
                "reply": "NutriAdvisor hiện tại chỉ hỗ trợ các chức năng: (1) Gợi ý thực đơn nhanh, (2) Tra cứu dinh dưỡng món ăn, và (3) Tìm món thay thế tương đương. Câu hỏi của bạn không nằm trong phạm vi hỗ trợ của hệ thống."
            }

        return {
            "status": "success",
            "intent": chat_intent,
            "entities": entities,
            "confidence": nlp_result.confidence,
            "source": nlp_result.source
        }

    def to_csp_payload(self, nlp_result: NLPResult) -> dict[str, Any]:
        """Convert an NLPResult into a minimal CSP payload contract.

        The payload contains user metadata, constraints, candidate variables
        (food items), and simple objectives that a downstream CSP solver can use.
        """
        entities = (nlp_result.entities or {})

        user = {}
        profile = entities.get("profile_updates") or {}
        for k in ("weight_kg", "height_cm", "daily_calorie_target"):
            if profile.get(k) is not None:
                user[k] = profile.get(k)

        constraints: dict[str, Any] = {
            "exclude": entities.get("allergies", []),
            "dietary_restrictions": entities.get("dietary_restrictions", []),
        }
        if entities.get("budget_vnd") is not None:
            constraints["budget_vnd_max"] = entities.get("budget_vnd")

        # Variables: candidate food items (normalized strings)
        candidates_raw = list(dict.fromkeys(str(v) for v in entities.get("food_items", []) if v))

        # Resolve names to ids and return structured candidates in all cases
        try:
            from .mapping import resolve_name

            mapped = []
            price_index = {}
            if self.price_defaults:
                if isinstance(self.price_defaults.get("indices"), dict):
                    indices = self.price_defaults.get("indices", {}) or {}
                    price_index = indices.get("by_name_vi") or indices.get("by_canonical_key") or {}
                else:
                    price_index = self.price_defaults.get("items", {}) or {}

            for name in candidates_raw:
                fid = resolve_name(name, self.food_mapping) if self.food_mapping else None
                candidate = {"id": fid, "name": name}
                
                # Attach estimated cost per 100g if price defaults have been loaded
                if price_index:
                    # Look up priority: matched ID, then extracted name
                    lookup_key = fid if fid and fid in price_index else name
                    if lookup_key in price_index:
                        value = price_index[lookup_key]
                        candidate["cost_vnd_100g"] = value.get("price_100g") if isinstance(value, dict) else value
                    else:
                        # Use fallback global average
                        candidate["cost_vnd_100g"] = self.price_defaults.get("global_average_100g", 15000)
                else:
                    # Use fallback global average
                    candidate["cost_vnd_100g"] = self.price_defaults.get("global_average_100g", 15000) if self.price_defaults else 15000
                        
                mapped.append(candidate)
        except Exception:
            # Complete robust fallback keeping the spec schema
            mapped = [{"id": None, "name": name, "cost_vnd_100g": 15000} for name in candidates_raw]
        variables = {"candidates": mapped}

        # Objectives: by default prefer nutrients requested
        nutrients = list(dict.fromkeys(str(v) for v in entities.get("nutrients", []) if v))
        objectives: dict[str, list[str]] = {"maximize": [], "minimize": []}
        if nutrients:
            objectives["maximize"].extend(nutrients)

        # If replacement_target exists, add as special constraint
        if entities.get("replacement_target"):
            constraints["replacement_target"] = entities.get("replacement_target")

        payload = {
            "user": user,
            "goal": {"type": nlp_result.intent},
            "constraints": constraints,
            "variables": variables,
            "objectives": objectives,
            "meta": {"query_keyword": entities.get("query_keyword"), "source": nlp_result.source, "cached_from": nlp_result.cached_from},
        }

        return payload

    def _is_profile_update_statement(self, user_query: str, entities: dict[str, Any]) -> bool:
        q = (user_query or "").lower()
        # If we detected an explicit weight value in profile_updates (not weight_change),
        # and the sentence does not contain recommendation cues, treat as profile update.
        rec_cues = ["gợi ý", "goi y", "thực đơn", "thuc don", "gợi ý thực phẩm", "gợi ý thực đơn", "gợi ý món", "muốn gợi ý", "gợi ý"]
        has_rec_cue = any(cue in q for cue in rec_cues)
        profile = entities.get("profile_updates", {}) or {}
        # consider any non-empty profile field (height, weight, birth_year, gender, calories)
        has_profile_field = any(
            profile.get(k) is not None for k in ("weight_kg", "height_cm", "birth_year", "gender", "daily_calorie_target")
        )
        has_weight_change = entities.get("weight_change_kg") is not None

        return has_profile_field and not has_rec_cue and not has_weight_change

    def _coerce_example(self, example: TrainingExample | dict[str, Any] | tuple[str, str]) -> tuple[str, str]:
        if isinstance(example, TrainingExample):
            return example.text.strip(), example.intent.strip()

        if isinstance(example, tuple):
            text, intent = example
            return str(text).strip(), str(intent).strip()

        text = str(example.get("text", "")).strip()
        intent = str(example.get("intent", "")).strip()
        return text, intent

    def _save_artifacts(self) -> None:
        payload = {
            "vectorizer": self.vectorizer,
            "classifier": self.classifier,
            "is_trained": True,
            "training_data_mtime": self._training_data_mtime(),
        }
        with open(self.model_dir / MODEL_ARTIFACT_NAME, "wb") as handle:
            pickle.dump(payload, handle)

    def _load_artifacts(self) -> bool:
        artifact_path = self.model_dir / MODEL_ARTIFACT_NAME
        if not artifact_path.exists():
            return False

        with open(artifact_path, "rb") as handle:
            payload = pickle.load(handle)

        saved_mtime = payload.get("training_data_mtime")
        current_mtime = self._training_data_mtime()
        if saved_mtime != current_mtime:
            return False

        self.vectorizer = payload["vectorizer"]
        self.classifier = payload["classifier"]
        self.is_trained = bool(payload.get("is_trained", True))
        return True

    def _training_data_mtime(self) -> float | None:
        if not DEFAULT_DATA_PATH.exists():
            return None

        return DEFAULT_DATA_PATH.stat().st_mtime


def load_default_training_examples() -> list[TrainingExample]:
    """Load seed training examples from the packaged JSONL file."""

    if not DEFAULT_DATA_PATH.exists():
        return []

    examples: list[TrainingExample] = []
    with DEFAULT_DATA_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            examples.append(TrainingExample(text=str(payload["text"]), intent=str(payload["intent"])))
    return examples
