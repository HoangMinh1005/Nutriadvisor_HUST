"""Scheduler core utilizing backtracking and automated progressive multi-stage constraint relaxation."""
from __future__ import annotations

import logging
import os
import random
import time
from collections import Counter, OrderedDict
from typing import Any, Dict, List, Set, Tuple

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
from constraint import Problem

from .constraints import NutrientConstraints
from .objective import score_meal_plan
from .classification import (
    classify_food,
    get_dynamic_tags,
    is_single_bowl_meal,
    is_offal_or_blood,
    is_clean_protein_gym,
    is_gym_blacklisted,
    get_max_serving_g,
    is_high_quality_protein,
    is_standalone_main_dish,
    get_food_role,
    clean_category,
    violates_dietary_restrictions,
)


class MealScheduler:
    """Ties together constraints and solver logic to produce 7-day personal meal plans using pure Database layers."""

    _DOMAIN_CONTEXT_CACHE: OrderedDict[Tuple[Any, ...], Dict[str, Any]] = OrderedDict()
    _DOMAIN_CONTEXT_CACHE_MAX = 16

    def __init__(
        self,
        user_profile: Dict[str, Any],
        available_foods: List[Dict[str, Any]] | None = None,
        db_url: str | None = None,
        candidate_food_ids: List[int] | None = None,
    ) -> None:
        self.user = user_profile
        self.db_url = db_url if db_url is not None else os.getenv("DATABASE_URL")
        self.candidate_food_ids = candidate_food_ids
        
        self.is_gym = (
            float(self.user.get("daily_calorie_target") or 0.0) >= 2800.0
            or str(self.user.get("goal") or "").lower() == "gym"
            or "gym" in str(self.user.get("user_message") or "").lower()
            or (self.user.get("macro_ratios") or {}).get("protein", 0.0) >= 0.25
        )
        self.daily_target = float(self.user.get("daily_calorie_target") or 1800.0)
        
        self.foods = available_foods or self._load_foods()
        for f in self.foods:
            f["max_serving_g"] = get_max_serving_g(f, self.is_gym, self.daily_target)
            
        self.food_by_id = {int(f["food_id"]): f for f in self.foods}
        self._food_roles_cache: Dict[int, str] | None = None
        self._food_name_low_cache: Dict[int, str] | None = None
        self._portion_cache: OrderedDict[Tuple[Any, ...], Tuple[float, float, float, float]] = OrderedDict()
        self._portion_cache_max = 2048

    def _load_foods(self) -> List[Dict[str, Any]]:
        """Load candidate foods from PostgreSQL, falling back to a sample list for offline unit testing."""
        if not self.db_url:
            fallback_foods = [
                {"food_id": 1, "canonical_key": "uc_ga", "canonical_name_en": "Chicken Breast", "name_vi": "ức gà", "calories": 165, "protein": 31, "fat": 3.6, "carbs": 0, "cost_vnd_100g": 15000, "category": "thịt_gia_cầm", "source_name": "NIN", "source_priority": 1},
                {"food_id": 2, "canonical_key": "trung", "canonical_name_en": "Egg", "name_vi": "trứng", "calories": 155, "protein": 13, "fat": 11, "carbs": 1.1, "cost_vnd_100g": 4000, "category": "trứng", "source_name": "NIN", "source_priority": 1},
                {"food_id": 3, "canonical_key": "yen_mach", "canonical_name_en": "Oats", "name_vi": "yến mạch", "calories": 389, "protein": 16.9, "fat": 6.9, "carbs": 66.3, "cost_vnd_100g": 10000, "category": "tinh_bột", "source_name": "NIN", "source_priority": 1},
                {"food_id": 4, "canonical_key": "com_trang", "canonical_name_en": "White Rice", "name_vi": "cơm trắng", "calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28, "cost_vnd_100g": 1800, "category": "tinh_bột", "source_name": "NIN", "source_priority": 1},
                {"food_id": 5, "canonical_key": "thit_bo", "canonical_name_en": "Beef", "name_vi": "thịt bò", "calories": 250, "protein": 26, "fat": 15, "carbs": 0, "cost_vnd_100g": 25000, "category": "thịt_đỏ", "source_name": "NIN", "source_priority": 1},
                {"food_id": 6, "canonical_key": "ca_hoi", "canonical_name_en": "Salmon", "name_vi": "cá hồi", "calories": 208, "protein": 20, "fat": 13, "carbs": 0, "cost_vnd_100g": 45000, "category": "cá_hải_sản", "source_name": "NIN", "source_priority": 1},
                {"food_id": 7, "canonical_key": "sua_tuoi", "canonical_name_en": "Milk", "name_vi": "sữa tươi", "calories": 60, "protein": 3.2, "fat": 3.25, "carbs": 4.8, "cost_vnd_100g": 3000, "category": "sữa", "source_name": "NIN", "source_priority": 1},
                {"food_id": 8, "canonical_key": "chuoi", "canonical_name_en": "Banana", "name_vi": "chuối", "calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 22.8, "cost_vnd_100g": 2000, "category": "trái_cây", "source_name": "NIN", "source_priority": 1},
                {"food_id": 9, "canonical_key": "rau_cai", "canonical_name_en": "Cabbage", "name_vi": "rau cải", "calories": 25, "protein": 1.3, "fat": 0.1, "carbs": 5.8, "cost_vnd_100g": 1500, "category": "rau_xanh", "source_name": "NIN", "source_priority": 1},
                {"food_id": 10, "canonical_key": "thit_vit", "canonical_name_en": "Duck", "name_vi": "thịt vịt", "calories": 337, "protein": 19, "fat": 28, "carbs": 0, "cost_vnd_100g": 18000, "category": "thịt_gia_cầm", "source_name": "NIN", "source_priority": 1},
            ]
            for f in fallback_foods:
                f["tags"] = get_dynamic_tags(f)
                f["meal_role"] = classify_food(f)
            return fallback_foods

        foods_list: List[Dict[str, Any]] = []
        try:
            query = """
                SELECT 
                    f.food_id, f.canonical_key, f.canonical_name_en, f.name_vi,
                    n.energy_kcal, n.protein_g, n.fat_g, n.carbs_g,
                    COALESCE(f.price_100g_vnd, 15000) AS price_100g,
                    g.group_code AS category,
                    f.source_name, f.source_priority,
                    f.tags, f.meal_role
                FROM foods f
                JOIN food_nutrients n ON f.food_id = n.food_id
                JOIN food_groups g ON f.food_group_id = g.food_group_id
                WHERE f.is_active = TRUE;
            """
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    for row in cur.fetchall():
                        fid, key, name_en, name_vi, cal, prot, fat, carb, price, category, src_name, src_priority, tags_array, meal_role = row
                        row_tags = set(tags_array) if tags_array else set()
                        
                        assigned_role = classify_food({"name_vi": name_vi, "category": category, "tags": row_tags, "carbs_g": carb, "fat_g": fat})
                        
                        actual_price = float(price or 15000)
                        if actual_price > 50000: 
                            actual_price = 22000.0  

                        foods_list.append({
                            "food_id": int(fid),
                            "canonical_key": key,
                            "canonical_name_en": name_en,
                            "name_vi": name_vi,
                            "calories": float(cal or 0),
                            "protein": float(prot or 0),
                            "fat": float(fat or 0),
                            "carbs": float(carb or 0),
                            "cost_vnd_100g": actual_price,
                            "category": category,
                            "source_name": src_name,
                            "source_priority": int(src_priority or 1),
                            "tags": row_tags,
                            "meal_role": assigned_role,
                        })
            return foods_list
        except Exception as exc:
            raise ConnectionError(f"CRITICAL: Failed to load food records natively from PostgreSQL: {exc}")

    def _get_food_roles_cache(self) -> Dict[int, str]:
        if self._food_roles_cache is None:
            self._food_roles_cache = {
                int(f["food_id"]): classify_food(f)
                for f in self.foods
            }
        return self._food_roles_cache

    def _get_food_name_low_cache(self) -> Dict[int, str]:
        if self._food_name_low_cache is None:
            self._food_name_low_cache = {
                int(f["food_id"]): str(f.get("name_vi") or "").lower()
                for f in self.foods
            }
        return self._food_name_low_cache

    def _effective_exclude_snacks(self, daily_target: float | None = None) -> bool:
        target = float(daily_target if daily_target is not None else self.daily_target)
        dietary_restrictions = {
            str(r).strip().lower()
            for r in (self.user.get("dietary_restrictions") or [])
            if str(r).strip()
        }
        snack_threshold = float(self.user.get("enable_snack_from_kcal") or 2400.0)
        if target >= 1600.0 and {"vegetarian", "vegan"}.intersection(dietary_restrictions):
            return False
        if target >= 2200.0 and dietary_restrictions:
            return False
        if target >= snack_threshold:
            return False
        return bool(self.user.get("exclude_snacks", False))

    def _max_occurrences_for_food(self, food_id: int, constraints: NutrientConstraints, plant_restricted: bool) -> int:
        """Diet-specific repeat limit.

        Plant-based and other restricted plans have a smaller feasible protein
        domain. A strict weekly cap of 3 can make 7-day plans impossible before
        nutrition is even evaluated, especially above 2200 kcal.
        """
        food = self.food_by_id.get(int(food_id), {})
        role = self._get_food_roles_cache().get(int(food_id), classify_food(food))
        name_low = self._get_food_name_low_cache().get(int(food_id), str(food.get("name_vi") or "").lower())
        target = float(constraints.daily_calorie_target or self.daily_target or 0.0)
        base_limit = int(self.user.get("max_food_occurrences_per_week") or constraints.max_food_occurrences_per_week or 3)

        if plant_restricted:
            if self._is_quail_egg_name(name_low):
                return 1
            if self._is_egg_name(name_low):
                return 2
            if self._is_tofu_name(name_low):
                return 4 if target >= 2200.0 else 3
            if role == "PLANT_PROTEIN":
                return 5 if target >= 2200.0 else 4
            if role == "STAPLE_CARB":
                return 7
            if role == "FIBER_SIDE":
                return 5
            return 5

        if self.user.get("dietary_restrictions") and target >= 2200.0:
            if role in {"MAIN_PROTEIN", "STAPLE_CARB"}:
                return 5
            return 4

        return base_limit

    @staticmethod
    def _is_egg_name(name_low: str) -> bool:
        return any(k in name_low for k in ["trứng", "trung", "egg", "yolk", "lòng đỏ", "lòng trắng"])

    @staticmethod
    def _is_quail_egg_name(name_low: str) -> bool:
        return any(k in name_low for k in ["trứng cút", "trứng chim cút", "trung cut", "trung chim cut", "quail egg"])

    @staticmethod
    def _is_chicken_egg_name(name_low: str) -> bool:
        return any(k in name_low for k in ["trứng gà", "trung ga", "chicken egg", "hen egg"])

    @staticmethod
    def _is_tofu_name(name_low: str) -> bool:
        return any(k in name_low for k in ["đậu phụ", "dau phu", "tofu", "tàu hũ", "tau hu"])

    def _food_repeat_family(self, food_id: int) -> str:
        name_low = self._get_food_name_low_cache().get(int(food_id), "")
        if self._is_quail_egg_name(name_low):
            return "egg_quail"
        if self._is_chicken_egg_name(name_low):
            return "egg_chicken"
        if self._is_egg_name(name_low):
            return "egg_other"
        if self._is_tofu_name(name_low):
            return "plant_tofu"
        role = self._get_food_roles_cache().get(int(food_id), "ACCESSORY_CONDIMENT")
        if role == "PLANT_PROTEIN":
            return f"plant:{int(food_id)}"
        return f"food:{int(food_id)}"

    def _domain_context_cache_key(
        self,
        domain_foods: List[Dict[str, Any]],
        constraints: NutrientConstraints,
        candidate_rank: Dict[int, int],
    ) -> Tuple[Any, ...]:
        macro = constraints.macro_ratios or {}
        food_signature = tuple(sorted(
            (
                int(f["food_id"]),
                round(float(f.get("calories") or 0.0), 2),
                round(float(f.get("protein") or 0.0), 2),
                round(float(f.get("fat") or 0.0), 2),
                round(float(f.get("carbs") or 0.0), 2),
                round(float(f.get("cost_vnd_100g") or 0.0), 0),
            )
            for f in domain_foods
        ))
        return (
            food_signature,
            tuple(sorted(str(a).lower().strip() for a in (self.user.get("allergies") or []) if str(a).strip())),
            tuple(sorted(str(r).lower().strip() for r in (self.user.get("dietary_restrictions") or []) if str(r).strip())),
            bool(self.is_gym),
            int(round(float(constraints.daily_calorie_target or 0.0))),
            int(round(float(constraints.budget_vnd_max or 0.0))),
            round(float(macro.get("protein", 0.3)), 3),
            round(float(macro.get("fat", 0.3)), 3),
            round(float(macro.get("carbs", 0.4)), 3),
            tuple(sorted(candidate_rank.items())[:400]),
        )

    def _get_or_build_domain_context(
        self,
        domain_foods: List[Dict[str, Any]],
        constraints: NutrientConstraints,
        candidate_rank: Dict[int, int],
    ) -> Dict[str, Any]:
        cache_key = self._domain_context_cache_key(domain_foods, constraints, candidate_rank)
        cached = self._DOMAIN_CONTEXT_CACHE.get(cache_key)
        if cached is not None:
            self._DOMAIN_CONTEXT_CACHE.move_to_end(cache_key)
            return cached

        context = self._build_domain_context(domain_foods, constraints, candidate_rank)
        self._DOMAIN_CONTEXT_CACHE[cache_key] = context
        self._DOMAIN_CONTEXT_CACHE.move_to_end(cache_key)
        while len(self._DOMAIN_CONTEXT_CACHE) > self._DOMAIN_CONTEXT_CACHE_MAX:
            self._DOMAIN_CONTEXT_CACHE.popitem(last=False)
        return context

    def _food_prune_score(
        self,
        food: Dict[str, Any],
        role: str,
        constraints: NutrientConstraints,
        candidate_rank: Dict[int, int],
        gym_priority: Dict[int, int],
    ) -> float:
        fid = int(food["food_id"])
        calories = float(food.get("calories") or 0.0)
        protein = float(food.get("protein") or 0.0)
        fat = float(food.get("fat") or 0.0)
        carbs = float(food.get("carbs") or 0.0)
        cost = float(food.get("cost_vnd_100g") or 15000.0)
        src_priority = float(food.get("source_priority") or 1.0)
        sim_rank = float(candidate_rank.get(fid, len(candidate_rank) + 50))
        daily_budget = max(float(constraints.budget_vnd_max or 200000.0), 1.0)
        name_low = str(food.get("name_vi") or "").lower()

        score = src_priority * 8.0 + sim_rank * 0.02 + (cost / daily_budget) * 80.0
        if role == "protein":
            protein_density = protein / max(calories, 1.0)
            score += gym_priority.get(fid, 2) * 24.0
            score -= protein_density * 260.0
            score += max(fat - protein, 0.0) * 1.5
            restriction_set = {
                str(r).strip().lower()
                for r in (self.user.get("dietary_restrictions") or [])
                if str(r).strip()
            }
            if "vegetarian" in restriction_set:
                if self._is_quail_egg_name(name_low):
                    score += 260.0
                elif self._is_chicken_egg_name(name_low):
                    score -= 45.0
                elif self._is_egg_name(name_low):
                    score += 40.0
        elif role == "carb":
            score += abs(calories - 160.0) * 0.03
            score -= carbs * 0.35
            score += fat * 1.0
        elif role == "fiber":
            score += calories * 0.04
            score -= (protein + carbs) * 0.15
        elif role == "breakfast":
            score += abs(calories - 260.0) * 0.025
            score += max(fat - 12.0, 0.0) * 1.0
        elif role == "snack":
            score += abs(calories - 120.0) * 0.035
            score += max(fat - 8.0, 0.0) * 1.0
        return score

    def _prune_food_pool(
        self,
        foods: List[Dict[str, Any]],
        role: str,
        limit: int,
        constraints: NutrientConstraints,
        candidate_rank: Dict[int, int],
        gym_priority: Dict[int, int],
        preserve_ids: Set[int] | None = None,
    ) -> List[Dict[str, Any]]:
        if len(foods) <= limit:
            return foods

        preserve_ids = preserve_ids or set()
        preserved = [f for f in foods if int(f["food_id"]) in preserve_ids]
        remaining = [f for f in foods if int(f["food_id"]) not in preserve_ids]
        remaining.sort(key=lambda f: self._food_prune_score(f, role, constraints, candidate_rank, gym_priority))
        pruned = preserved + remaining[:max(0, limit - len(preserved))]
        return list({int(f["food_id"]): f for f in pruned}.values())

    def _prune_id_pool(
        self,
        ids: List[int],
        role: str,
        limit: int,
        constraints: NutrientConstraints,
        candidate_rank: Dict[int, int],
        gym_priority: Dict[int, int],
    ) -> List[int]:
        if len(ids) <= limit:
            return ids
        ids = list(dict.fromkeys(ids))
        ids.sort(key=lambda fid: self._food_prune_score(self.food_by_id[fid], role, constraints, candidate_rank, gym_priority))
        return ids[:limit]

    def _build_domain_context(
        self,
        domain_foods: List[Dict[str, Any]],
        constraints: NutrientConstraints,
        candidate_rank: Dict[int, int],
    ) -> Dict[str, Any]:
        """Precompute domain-level classifications that are reused across CSP attempts."""
        food_roles_cache = self._get_food_roles_cache()
        food_name_low = self._get_food_name_low_cache()

        all_carbs, all_proteins, all_plant_proteins, all_fibers, all_snacks = [], [], [], [], []
        fallback_carbs, fallback_proteins, fallback_plant_proteins, fallback_fibers = [], [], [], []
        breakfast_ids, lunch_ids, dinner_ids, snack_ids = [], [], [], []
        offal_ids: Set[int] = set()
        gym_priority: Dict[int, int] = {}
        restriction_set = {
            str(r).strip().lower()
            for r in (self.user.get("dietary_restrictions") or [])
            if str(r).strip()
        }
        use_plant_protein_as_core = bool(
            self.user.get("plant_protein_as_core")
            or {"vegetarian", "vegan"}.intersection(restriction_set)
        )

        allergy_input = [str(a).lower() for a in (self.user.get("allergies") or [])]
        has_seafood_allergy = any(("hải sản" in a or "seafood" in a) for a in allergy_input if a.strip())

        for f in domain_foods:
            fid = int(f["food_id"])
            role = food_roles_cache[fid]
            tags = f.get("tags") or set()
            cat_clean = clean_category(f.get("category"))
            name_vi = food_name_low.get(fid, "")

            if role == "STAPLE_CARB":
                fallback_carbs.append(f)
            elif role == "MAIN_PROTEIN":
                fallback_proteins.append(f)
            elif role == "PLANT_PROTEIN":
                fallback_plant_proteins.append(f)
            elif role == "FIBER_SIDE":
                fallback_fibers.append(f)

            if role == "ACCESSORY_CONDIMENT":
                if "is_dessert_snack" in tags or cat_clean == "trai_cay":
                    all_snacks.append(f)
                continue

            if role == "STAPLE_CARB":
                all_carbs.append(f)
            elif role == "MAIN_PROTEIN":
                all_proteins.append(f)
            elif role == "PLANT_PROTEIN":
                all_plant_proteins.append(f)
            elif role == "FIBER_SIDE":
                all_fibers.append(f)

            if has_seafood_allergy and any(k in name_vi for k in ["trai", "hến", "nghêu", "sò", "ốc", "hàu", "tôm", "cua", "mực", "sứa", "bề bề"]):
                continue
            if any(k in name_vi for k in ["châu chấu", "chau chau", "cào cào", "cao cao", "nhộng", "nhong", "đuông dừa"]):
                continue

            if any(k in name_vi for k in ["giò lụa", "gio lua", "chả quế", "cha que", "chả lụa"]):
                f["max_serving_g"] = 120.0

            is_valid_vietnamese_breakfast = any(k in name_vi for k in ["bún", "miến", "phở", "cháo", "xôi", "bánh mì", "bánh mỳ", "bánh cuốn"])
            is_snack_cake = any(k in name_vi for k in ["bánh nếp", "bánh trôi", "bánh chay", "bánh tẻ", "bánh gio", "bánh cốm", "bánh rán", "bánh đa nem", "bánh quẩy", "bánh mì, vuông, ngọt"])

            if is_valid_vietnamese_breakfast and not is_snack_cake:
                breakfast_ids.append(fid)
            if (role == "MAIN_PROTEIN" or (use_plant_protein_as_core and role == "PLANT_PROTEIN")) and not is_snack_cake:
                lunch_ids.append(fid)
                dinner_ids.append(fid)
            snack_ids.append(fid)

            if is_offal_or_blood(f):
                offal_ids.add(fid)

            if self.is_gym:
                is_clean = "clean_protein" in tags or is_clean_protein_gym(f)
                if is_clean:
                    if any(k in name_vi for k in ["ức gà", "lườn gà", "gà công nghiệp", "cá hồi", "cá ngừ", "cá quả", "cá chép", "thăn bò", "bắp bò"]):
                        gym_priority[fid] = 0
                    else:
                        gym_priority[fid] = 1
                else:
                    gym_priority[fid] = 2

        target_calories = float(constraints.daily_calorie_target or 1800.0)
        protein_limit = 130 if self.is_gym or target_calories >= 2400.0 else 105
        carb_limit = 85 if target_calories >= 2400.0 else 70
        fiber_limit = 80
        breakfast_limit = 65
        snack_limit = 65

        effective_carbs = all_carbs or fallback_carbs
        protein_pool = all_proteins + all_plant_proteins if use_plant_protein_as_core else all_proteins
        fallback_protein_pool = fallback_proteins + fallback_plant_proteins if use_plant_protein_as_core else fallback_proteins
        effective_proteins = protein_pool or fallback_protein_pool
        effective_fibers = all_fibers or fallback_fibers
        if not all_snacks:
            all_snacks = domain_foods

        rice_food = next(
            (f for f in effective_carbs if any(k in food_name_low.get(int(f["food_id"]), "") for k in ["cơm tẻ", "cơm trắng", "cơm chín"])),
            None,
        )
        if not rice_food and effective_carbs:
            rice_food = effective_carbs[0]

        preserve_carb_ids = {int(rice_food["food_id"])} if rice_food else set()
        effective_carbs = self._prune_food_pool(
            effective_carbs, "carb", carb_limit, constraints, candidate_rank, gym_priority, preserve_carb_ids
        )
        effective_proteins = self._prune_food_pool(
            effective_proteins, "protein", protein_limit, constraints, candidate_rank, gym_priority
        )
        effective_fibers = self._prune_food_pool(
            effective_fibers, "fiber", fiber_limit, constraints, candidate_rank, gym_priority
        )
        all_snacks = self._prune_food_pool(
            all_snacks, "snack", snack_limit, constraints, candidate_rank, gym_priority
        )

        alternative_carbs = [
            f for f in effective_carbs
            if not any(k in food_name_low.get(int(f["food_id"]), "") for k in ["cơm tẻ", "cơm trắng", "cơm chín", "bánh ngọt", "bánh trôi", "bánh chay"])
        ]
        clean_proteins = [f for f in effective_proteins if is_clean_protein_gym(f)]

        unique_breakfast_ids = list(dict.fromkeys(breakfast_ids))
        unique_lunch_ids = list(dict.fromkeys(lunch_ids))
        unique_dinner_ids = list(dict.fromkeys(dinner_ids))
        unique_snack_ids = list(dict.fromkeys(snack_ids))
        unique_lunch_ids.sort(key=lambda fid: gym_priority.get(fid, 2))
        unique_dinner_ids.sort(key=lambda fid: gym_priority.get(fid, 2))
        unique_breakfast_ids = self._prune_id_pool(
            unique_breakfast_ids, "breakfast", breakfast_limit, constraints, candidate_rank, gym_priority
        )
        unique_lunch_ids = self._prune_id_pool(
            unique_lunch_ids, "protein", protein_limit, constraints, candidate_rank, gym_priority
        )
        unique_dinner_ids = self._prune_id_pool(
            unique_dinner_ids, "protein", protein_limit, constraints, candidate_rank, gym_priority
        )
        unique_snack_ids = self._prune_id_pool(
            unique_snack_ids, "snack", snack_limit, constraints, candidate_rank, gym_priority
        )

        return {
            "roles": food_roles_cache,
            "names": food_name_low,
            "all_carbs": effective_carbs,
            "all_proteins": effective_proteins,
            "all_fibers": effective_fibers,
            "all_snacks": all_snacks,
            "rice_food": rice_food,
            "alternative_carbs": alternative_carbs,
            "clean_proteins": clean_proteins,
            "clean_fibers": effective_fibers,
            "fallback_carbs": [int(f["food_id"]) for f in effective_carbs[:30]],
            "fallback_proteins": [int(f["food_id"]) for f in effective_proteins[:30]],
            "breakfast_ids": unique_breakfast_ids,
            "lunch_ids": unique_lunch_ids,
            "dinner_ids": unique_dinner_ids,
            "snack_ids": unique_snack_ids,
            "offal_ids": offal_ids,
            "gym_priority": gym_priority,
            "has_allergies": bool(self.user.get("allergies")),
        }

    def solve_with_relaxation(self, max_attempts: int = 4) -> Dict[str, Any]:
        """Solver orchestration wrapping the auto-relaxation loops."""
        dietary_restrictions = self.user.get("dietary_restrictions") or []
        restriction_set = {
            str(r).strip().lower()
            for r in dietary_restrictions
            if str(r).strip()
        }
        use_plant_protein_as_core = bool(
            self.user.get("plant_protein_as_core")
            or {"vegetarian", "vegan"}.intersection(restriction_set)
        )
        has_dietary_restrictions = bool(restriction_set)
        constraints = NutrientConstraints(
            daily_calorie_target=float(self.user.get("daily_calorie_target") or 1800.0),
            calorie_tolerance_pct=float(
                self.user.get("calorie_tolerance_pct")
                or (0.15 if use_plant_protein_as_core else 0.12)
            ),
            macro_ratios=self.user.get("macro_ratios"),
            macro_tolerance_pct=float(
                self.user.get("macro_tolerance_pct")
                or (0.18 if use_plant_protein_as_core else 0.12)
            ),
            allergies=self.user.get("allergies"),
            budget_vnd_max=self.user.get("budget_vnd_max") or 200000.0,
            max_food_occurrences_per_week=3,
            min_budget_floor_pct=0.0 if has_dietary_restrictions else 0.55,
        )

        domain_foods = self.foods
        if self.candidate_food_ids is not None:
            domain_foods = [f for f in domain_foods if int(f["food_id"]) in self.candidate_food_ids]
        if constraints.allergies:
            domain_foods = [f for f in domain_foods if constraints.check_allergies([f])]
        if dietary_restrictions:
            domain_foods = [f for f in domain_foods if not violates_dietary_restrictions(f, dietary_restrictions)]
        if self.is_gym:
            domain_foods = [f for f in domain_foods if not is_gym_blacklisted(f)]
        if not domain_foods:
            return {
                "status": "infeasible",
                "feasible": False,
                "meal_plan": [],
                "relaxation_attempts": 0,
            }

        MAX_DOMAIN_SIZE = 180
        candidate_rank = {
            int(fid): idx for idx, fid in enumerate(self.candidate_food_ids or [])
        }
        if len(domain_foods) > MAX_DOMAIN_SIZE:
            def domain_sort_key(f):
                fid = int(f["food_id"])
                src_pri = int(f.get("source_priority") or 1)
                role = classify_food(f)
                plant_priority = 0 if use_plant_protein_as_core and role == "PLANT_PROTEIN" else 1
                
                is_clean_p = 0
                if self.is_gym:
                    tags = f.get("tags") or set()
                    name_low = str(f.get("name_vi") or "").lower()
                    is_clean = "clean_protein" in tags or is_clean_protein_gym(f)
                    if is_clean:
                        if any(k in name_low for k in ["ức gà", "lườn gà", "gà công nghiệp", "thăn bò", "bắp bò", "bò, loại i", "bò, lưng, nạc", "thăn lợn", "thăn heo", "lợn, loại i", "heo, loại i", "cá hồi", "cá ngừ", "cá quả", "cá chép", "thịt trắm", "basa", "chim", "điêu hồng"]):
                            is_clean_p = 1
                        else:
                            is_clean_p = 2
                    else:
                        is_clean_p = 3
                
                sim_idx = candidate_rank.get(fid, len(candidate_rank))
                        
                return (plant_priority, src_pri, is_clean_p, sim_idx) if self.is_gym else (plant_priority, src_pri, sim_idx)

            domain_foods.sort(key=domain_sort_key)
            domain_foods = domain_foods[:MAX_DOMAIN_SIZE]

        domain_context = self._get_or_build_domain_context(domain_foods, constraints, candidate_rank)

        attempt = 1
        tolerance_multiplier = 1.0
        time_budget_seconds = float(self.user.get("csp_time_budget_seconds") or os.getenv("CSP_TIME_BUDGET_SECONDS") or 3.0)
        if use_plant_protein_as_core:
            time_budget_seconds = max(time_budget_seconds, 7.0 if self.daily_target >= 2200.0 else 5.0)
        elif has_dietary_restrictions and self.daily_target >= 2200.0:
            time_budget_seconds = max(time_budget_seconds, 5.0)
        deadline = time.perf_counter() + max(0.75, time_budget_seconds)

        while attempt <= max_attempts:
            logging.getLogger(__name__).info(
                "CSP Solve Attempt %s/%s (multiplier=%.2f)", attempt, max_attempts, tolerance_multiplier
            )
            result = self._solve(domain_foods, constraints, tolerance_multiplier, domain_context, deadline)
            if result["feasible"]:
                result["relaxation_attempts"] = attempt
                return result
            if time.perf_counter() >= deadline:
                break

            tolerance_multiplier += 0.25
            attempt += 1

        return {
            "status": "infeasible",
            "feasible": False,
            "meal_plan": [],
            "relaxation_attempts": max_attempts,
        }

    def _portion_cache_key(
        self,
        preclassified_components: List[Tuple[float, float, float, float, str, float]],
        constraints: NutrientConstraints,
        tolerance_multiplier: float,
    ) -> Tuple[Any, ...]:
        macro = constraints.macro_ratios or {}
        component_key = tuple(
            (
                round(cal, 3),
                round(protein, 3),
                round(fat, 3),
                round(carbs, 3),
                w_type,
                round(max_w, 1),
            )
            for cal, protein, fat, carbs, w_type, max_w in preclassified_components
        )
        return (
            component_key,
            int(round(float(constraints.daily_calorie_target or 0.0))),
            round(float(constraints.calorie_tolerance_pct or 0.0), 3),
            round(float(tolerance_multiplier), 2),
            round(float(macro.get("protein", 0.3)), 3),
            round(float(macro.get("fat", 0.3)), 3),
            round(float(macro.get("carbs", 0.4)), 3),
        )

    def _remember_portion_cache(
        self,
        key: Tuple[Any, ...],
        value: Tuple[float, float, float, float],
    ) -> None:
        self._portion_cache[key] = value
        self._portion_cache.move_to_end(key)
        while len(self._portion_cache) > self._portion_cache_max:
            self._portion_cache.popitem(last=False)

    def _find_best_portions(
        self,
        preclassified_components: List[Tuple[float, float, float, float, str, float]],
        constraints: NutrientConstraints,
        tolerance_multiplier: float,
        w_prot_space: List[float],
        w_crb_space: List[float],
        w_fix_space: List[float],
    ) -> Tuple[float, float, float, float]:
        cache_key = self._portion_cache_key(preclassified_components, constraints, tolerance_multiplier)
        cached = self._portion_cache.get(cache_key)
        if cached is not None:
            self._portion_cache.move_to_end(cache_key)
            return cached

        p_ratio = constraints.macro_ratios.get("protein", 0.4)
        c_ratio = constraints.macro_ratios.get("carbs", 0.3)
        f_ratio = constraints.macro_ratios.get("fat", 0.3)
        best_w_protein, best_w_carb, best_w_fixed = 150.0, 150.0, 100.0
        min_error = float("inf")

        tolerance = constraints.daily_calorie_target * constraints.calorie_tolerance_pct * tolerance_multiplier
        min_cal = constraints.daily_calorie_target - tolerance
        max_cal = constraints.daily_calorie_target + tolerance

        for w_prot in w_prot_space:
            for w_crb in w_crb_space:
                for w_fix in w_fix_space:
                    total_cal, total_p, total_f, total_c = 0.0, 0.0, 0.0, 0.0

                    for f_cal, f_prot, f_fat, f_carb, w_type, max_w in preclassified_components:
                        if w_type == "fix":
                            w = w_fix
                        elif w_type == "crb":
                            w = w_crb
                        else:
                            w = w_prot

                        w = min(w, max_w)
                        factor = w / 100.0
                        total_cal += f_cal * factor
                        total_p += f_prot * factor
                        total_f += f_fat * factor
                        total_c += f_carb * factor

                    cal_error = abs(total_cal - constraints.daily_calorie_target) / constraints.daily_calorie_target
                    cal_penalty = 0.0 if min_cal <= total_cal <= max_cal else 1000.0

                    total_mass = total_p + total_f + total_c
                    if total_mass > 0:
                        macro_error = (
                            abs((total_p / total_mass) - p_ratio) * 6.0
                            + abs((total_f / total_mass) - f_ratio) * 1.5
                            + abs((total_c / total_mass) - c_ratio) * 1.5
                        )
                    else:
                        macro_error = 1.0

                    error = cal_error + macro_error + cal_penalty
                    if error < min_error:
                        min_error = error
                        best_w_protein, best_w_carb, best_w_fixed = w_prot, w_crb, w_fix

        value = (best_w_protein, best_w_carb, best_w_fixed, min_error)
        self._remember_portion_cache(cache_key, value)
        return value

    def _get_meal_plan_for_solution(
        self,
        sol: Dict[str, int],
        constraints: NutrientConstraints,
        tolerance_multiplier: float,
        all_carbs: List[Dict[str, Any]],
        all_proteins: List[Dict[str, Any]],
        all_fibers: List[Dict[str, Any]],
        all_snacks: List[Dict[str, Any]],
        day_excluded_ids: Set[int] | None = None,
        cached_roles: Dict[int, str] | None = None,
        rice_food: Dict[str, Any] | None = None,
        alternative_carbs: List[Dict[str, Any]] | None = None,
        clean_proteins: List[Dict[str, Any]] | None = None,
        clean_fibers: List[Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        """Dynamic cross-scaling solver that structurally builds verified Vietnamese meal plans."""
        def get_complementary(pool, excluded_ids=None, filter_chả_cá=False):
            if excluded_ids is None: excluded_ids = set()
            candidates = [f for f in pool if int(f["food_id"]) not in excluded_ids and 
                          (not day_excluded_ids or int(f["food_id"]) not in day_excluded_ids)]
            
            # CHẶN TUYỆT ĐỐI CHẢ CÁ LẶP Ở ĐÂY NẾU ĐƯỢC KÍCH HOẠT
            if filter_chả_cá:
                candidates = [c for c in candidates if not ("chả" in str(c.get("name_vi")).lower() and "cá" in str(c.get("name_vi")).lower())]

            if candidates:
                return random.choice(candidates[:min(12, len(candidates))])
            candidates_fallback = [f for f in pool if int(f["food_id"]) not in excluded_ids]
            if candidates_fallback:
                return random.choice(candidates_fallback[:min(5, len(candidates_fallback))])
            return pool[0] if pool else None

        def fast_classify(food_item: Dict[str, Any]) -> str:
            if cached_roles is not None:
                return cached_roles.get(int(food_item["food_id"]), "ACCESSORY_CONDIMENT")
            return classify_food(food_item)

        if not rice_food and all_carbs:
            rice_food = next((f for f in all_carbs if any(k in str(f.get("name_vi")).lower() for k in ["cơm tẻ", "cơm trắng", "cơm chín"])), None) or all_carbs[0]

        if alternative_carbs is None:
            alternative_carbs = [
                f for f in all_carbs
                if fast_classify(f) == "STAPLE_CARB"
                and not any(k in str(f.get("name_vi")).lower() for k in ["cơm tẻ", "cơm trắng", "cơm chín", "bánh ngọt", "bánh trôi", "bánh chay"])
            ]
        if clean_proteins is None:
            clean_proteins = [f for f in all_proteins if is_clean_protein_gym(f)]
        if clean_fibers is None:
            clean_fibers = [
                f for f in all_fibers
                if fast_classify(f) == "FIBER_SIDE"
            ]

        components = []
        excluded_ids = set()

        # 1. CẤU TRÚC BỮA SÁNG
        b_core = self.food_by_id[sol["breakfast"]]
        components.append({"slot": "breakfast", "food": b_core, "role": "core"})
        if self.is_gym and all_proteins and not is_standalone_main_dish(b_core):
            comp_b_prot = get_complementary(clean_proteins, excluded_ids)
            if comp_b_prot:
                components.append({"slot": "breakfast", "food": comp_b_prot, "role": "protein"})
                excluded_ids.add(comp_b_prot["food_id"])

        # 2. CẤU TRÚC BỮA TRƯA & TỐI
        for slot in ["lunch", "dinner"]:
            core_protein = self.food_by_id[sol[slot]]
            name_check = str(core_protein.get("name_vi") or "").lower()
            is_standalone = is_single_bowl_meal(core_protein) or any(k in name_check for k in ['bún', 'phở', 'cháo', 'miến', 'mỳ'])
            
            if is_standalone:
                components.append({"slot": slot, "food": core_protein, "role": "core"})
                if all_fibers:
                    comp_fiber = get_complementary(clean_fibers if clean_fibers else all_fibers, excluded_ids)
                    if comp_fiber:
                        components.append({"slot": slot, "food": comp_fiber, "role": "fiber"})
                        excluded_ids.add(comp_fiber["food_id"])
            else:
                chosen_carb = rice_food
                if alternative_carbs and random.random() < 0.40:
                    chosen_carb = get_complementary(alternative_carbs, excluded_ids) or rice_food

                if chosen_carb:
                    components.append({"slot": slot, "food": chosen_carb, "role": "carb"})
                    excluded_ids.add(chosen_carb["food_id"])

                # KIỂM TRA: Nếu món core_protein bốc trúng chả cá basa lặp, ta lọc mềm pool
                is_chả_cá = "chả" in name_check and "cá" in name_check
                actual_protein_food = core_protein
                if is_chả_cá and day_excluded_ids and len(day_excluded_ids) > 5:
                    # Đổi sang món đạm sạch khác không phải chả cá băm viên
                    alt_protein = get_complementary(all_proteins, excluded_ids, filter_chả_cá=True)
                    if alt_protein:
                        actual_protein_food = alt_protein

                components.append({"slot": slot, "food": actual_protein_food, "role": "protein"})
                excluded_ids.add(actual_protein_food["food_id"])
                
                if all_fibers:
                    clean_fibers_for_carb = [
                        f for f in clean_fibers
                        if f["food_id"] != chosen_carb["food_id"]
                    ]
                    comp_fiber = get_complementary(clean_fibers_for_carb if clean_fibers_for_carb else all_fibers, excluded_ids)
                    if comp_fiber:
                        components.append({"slot": slot, "food": comp_fiber, "role": "fiber"})
                        excluded_ids.add(comp_fiber["food_id"])

        daily_target = float(self.user.get("daily_calorie_target") or 1800.0)
        exclude_snacks = self._effective_exclude_snacks(daily_target)
        if not exclude_snacks and sol.get("snack"):
            components.append({"slot": "snack", "food": self.food_by_id[sol["snack"]], "role": "snack"})

        if daily_target <= 1200.0:
            w_prot_space = [70.0, 100.0, 150.0]
            w_crb_space = [70.0, 100.0, 140.0]
            w_fix_space = [50.0, 75.0, 100.0]
        elif daily_target >= 3000.0:
            w_prot_space = [220.0, 280.0, 340.0, 400.0, 460.0, 520.0]
            w_crb_space = [180.0, 240.0, 300.0, 360.0, 420.0, 460.0]
            w_fix_space = [120.0, 160.0, 200.0, 240.0]
        elif daily_target >= 2200.0 and self.user.get("plant_protein_as_core"):
            w_prot_space = [180.0, 230.0, 280.0, 340.0, 400.0, 460.0]
            w_crb_space = [150.0, 200.0, 260.0, 320.0, 380.0]
            w_fix_space = [100.0, 140.0, 180.0, 220.0]
        elif daily_target >= 2400.0:
            w_prot_space = [180.0, 230.0, 280.0, 340.0, 400.0, 460.0] if self.is_gym else [150.0, 200.0, 250.0, 320.0, 400.0]
            w_crb_space = [150.0, 200.0, 260.0, 320.0, 380.0]
            w_fix_space = [100.0, 140.0, 180.0, 220.0]
        else:
            w_prot_space = [150.0, 180.0, 220.0, 260.0, 300.0, 350.0] if (self.is_gym and daily_target >= 1600.0) else [100.0, 150.0, 200.0]
            w_crb_space = [100.0, 140.0, 180.0, 220.0, 260.0, 300.0]
            w_fix_space = [100.0, 120.0, 150.0]

        preclassified_components = []
        for comp in components:
            f = comp["food"]
            slot = comp["slot"]
            role = comp.get("role", "core")
            
            if slot == "snack":
                w_type = "fix"
            else:
                is_cơm = "cơm" in str(f.get("name_vi")).lower()
                is_sub_carb = (fast_classify(f) == "STAPLE_CARB")
                current_role = fast_classify(f)
                role_protein = f.get("meal_role") in ["MAIN_PROTEIN", "PLANT_PROTEIN"] or current_role in ["MAIN_PROTEIN", "PLANT_PROTEIN"]
                if role == "carb" or is_cơm or is_sub_carb:
                    w_type = "crb"
                elif role in ["protein", "core"] and (is_standalone_main_dish(f) or role_protein):
                    w_type = "prot"
                else:
                    w_type = "fix"
            max_w = f.get("max_serving_g") or 450.0
            
            preclassified_components.append((
                float(f.get("calories") or 0.0),
                float(f.get("protein") or 0.0),
                float(f.get("fat") or 0.0),
                float(f.get("carbs") or 0.0),
                w_type,
                max_w
            ))

        best_w_protein, best_w_carb, best_w_fixed, min_error = self._find_best_portions(
            preclassified_components,
            constraints,
            tolerance_multiplier,
            w_prot_space,
            w_crb_space,
            w_fix_space,
        )

        if min_error == float("inf"):
            raise ValueError("No portion spacing matches criteria.")

        day_meals = []
        slots_to_generate = ["breakfast", "lunch", "dinner"] if exclude_snacks else ["breakfast", "lunch", "snack", "dinner"]
        
        for slot in slots_to_generate:
            slot_comps = [c for c in components if c["slot"] == slot]
            if not slot_comps: continue
            
            names_vi = []
            meal_cost, meal_cal, meal_p, meal_f, meal_c = 0.0, 0.0, 0.0, 0.0, 0.0
            
            components_data = []
            for comp in slot_comps:
                f = comp["food"]
                role = comp["role"]
                is_sub_carb = (fast_classify(f) == "STAPLE_CARB")
                if slot == "snack": w = best_w_fixed
                else:
                    if role == "carb" or "cơm" in str(f.get("name_vi")).lower() or is_sub_carb: w = best_w_carb
                    elif role in ["protein", "core"] and (is_standalone_main_dish(f) or fast_classify(f) in ["MAIN_PROTEIN", "PLANT_PROTEIN"]): w = best_w_protein
                    else: w = best_w_fixed
                max_w = f.get("max_serving_g") or 450.0
                w = min(w, max_w)
                
                factor = w / 100.0
                c_cost = float(f.get("cost_vnd_100g") or 15000) * factor
                c_cal = float(f.get("calories") or 0.0) * factor
                c_p = float(f.get("protein") or 0.0) * factor
                c_f = float(f.get("fat") or 0.0) * factor
                c_c = float(f.get("carbs") or 0.0) * factor
                
                meal_cost += c_cost
                meal_cal += c_cal
                meal_p += c_p
                meal_f += c_f
                meal_c += c_c
                
                display = f.get("name_vi") or f.get("canonical_name_en") or "Thực phẩm"
                display_clean = display
                for suffix in [" nguyên chất", " tươi", " sống", " chín", " luộc", " khô", ", tươi", ", sống", ", chín", ", luộc", ", khô", ", raw"]:
                    if display_clean.lower().endswith(suffix):
                        display_clean = display_clean[:-len(suffix)].strip()
                names_vi.append(f"{display_clean} ({int(w)}g)")
                
                components_data.append({
                    "food_id": int(f["food_id"]),
                    "name": display_clean,
                    "weight": float(w),
                    "calories": float(c_cal),
                    "protein": float(c_p),
                    "fat": float(c_f),
                    "carbs": float(c_c),
                    "cost_vnd_100g": float(f.get("cost_vnd_100g") or 15000)
                })

            day_meals.append({
                "meal_type": slot,
                "food_id": slot_comps[0]["food"]["food_id"],
                "name": " + ".join(names_vi),
                "total_cost_vnd": meal_cost,
                "calories": meal_cal,
                "protein": meal_p,
                "fat": meal_f,
                "carbs": meal_c,
                "component_food_ids": [c["food"]["food_id"] for c in slot_comps],
                "components": components_data,
            })

        return day_meals

    def _solve(
        self,
        domain_foods: List[Dict[str, Any]],
        constraints: NutrientConstraints,
        tolerance_multiplier: float,
        domain_context: Dict[str, Any],
        deadline: float | None = None,
    ) -> Dict[str, Any]:
        """Core sequential CSP engine with optimized pricing heuristics."""
        
        food_roles_cache = domain_context["roles"]
        food_name_low = domain_context["names"]
        all_carbs = domain_context["all_carbs"]
        all_proteins = domain_context["all_proteins"]
        all_fibers = domain_context["all_fibers"]
        all_snacks = domain_context["all_snacks"]
        dietary_restrictions = self.user.get("dietary_restrictions") or []
        plant_restricted = bool(
            self.user.get("plant_protein_as_core")
            or
            {"vegetarian", "vegan"}.intersection(
                {
                    str(r).strip().lower()
                    for r in dietary_restrictions
                    if str(r).strip()
                }
            )
        )
        diversity_penalty_weight = float(
            self.user.get("diversity_penalty_weight")
            or (0.35 if plant_restricted else 1.0)
        )
        macro_stability_weight = float(self.user.get("macro_stability_weight") or 1.0)

        exclude_snacks = self._effective_exclude_snacks()
        scheduled_plan = []
        used_food_ids = []
        offal_blood_count = 0

        for day in range(7):
            global_counts = Counter(used_food_ids)
            block_offal = self.is_gym or offal_blood_count >= 1
            offal_ids = domain_context["offal_ids"]

            def is_available_today(fid: int) -> bool:
                name_vi = food_name_low.get(fid, "")
                if block_offal and fid in offal_ids:
                    return False
                max_occurrences = self._max_occurrences_for_food(fid, constraints, plant_restricted)
                if global_counts[fid] >= max_occurrences and not ("cơm" in name_vi or "com" in name_vi):
                    return False
                return True

            breakfast_candidates = [fid for fid in domain_context["breakfast_ids"] if is_available_today(fid)]
            lunch_candidates = [fid for fid in domain_context["lunch_ids"] if is_available_today(fid)]
            dinner_candidates = [fid for fid in domain_context["dinner_ids"] if is_available_today(fid)]
            snack_foods = [fid for fid in domain_context["snack_ids"] if is_available_today(fid)]

            if not breakfast_candidates:
                breakfast_candidates = [fid for fid in domain_context["fallback_carbs"] if is_available_today(fid)]
            if not lunch_candidates:
                lunch_candidates = [fid for fid in domain_context["fallback_proteins"] if is_available_today(fid)]
            if not dinner_candidates:
                dinner_candidates = [fid for fid in domain_context["fallback_proteins"] if is_available_today(fid)]
            if plant_restricted:
                breakfast_candidates = list(dict.fromkeys(breakfast_candidates + list(domain_context["fallback_carbs"])))
                lunch_candidates = list(dict.fromkeys(lunch_candidates + list(domain_context["fallback_proteins"])))
                dinner_candidates = list(dict.fromkeys(dinner_candidates + list(domain_context["fallback_proteins"])))
                snack_foods = list(dict.fromkeys(snack_foods + list(domain_context["snack_ids"])))
            if not lunch_candidates:
                lunch_candidates = list(domain_context["fallback_proteins"])
            if not dinner_candidates:
                dinner_candidates = list(domain_context["fallback_proteins"])
            if not breakfast_candidates:
                breakfast_candidates = list(domain_context["fallback_carbs"])
            if not breakfast_candidates or not lunch_candidates or not dinner_candidates:
                return {"feasible": False, "meal_plan": []}

            random.shuffle(breakfast_candidates)

            prob = Problem()
            prob.addVariable("breakfast", breakfast_candidates[:50])
            prob.addVariable("lunch", lunch_candidates[:150])
            if not exclude_snacks:
                snack_candidates = snack_foods[:50]
                if not snack_candidates:
                    snack_candidates = list(domain_context["snack_ids"])[:50]
                prob.addVariable("snack", snack_candidates)
            prob.addVariable("dinner", dinner_candidates[:150])

            def check_inline_budget_and_habits(*args):
                b, l, d = args[0], args[1], args[-1]
                b_f, l_f, d_f = self.food_by_id[b], self.food_by_id[l], self.food_by_id[d]
                if domain_context["has_allergies"] and not constraints.check_allergies([b_f, l_f, d_f]): return False
                
                approx_cost = b_f.get("cost_vnd_100g", 15000) + l_f.get("cost_vnd_100g", 15000) + d_f.get("cost_vnd_100g", 15000)
                if approx_cost > constraints.budget_vnd_max: 
                    return False
                return True

            var_order = ["breakfast", "lunch", "snack", "dinner"] if not exclude_snacks else ["breakfast", "lunch", "dinner"]
            prob.addConstraint(check_inline_budget_and_habits, var_order)

            sols = prob.getSolutionIter()
            valid_scored = []
            checked_count = 0
            time_left = (deadline - time.perf_counter()) if deadline is not None else 999.0
            if time_left <= 0.25:
                MAX_CHECKED = 35
            elif time_left <= 0.75:
                MAX_CHECKED = 80
            else:
                MAX_CHECKED = 180
            previous_day_ids = set()
            if scheduled_plan:
                for prev_meal in scheduled_plan[-1].get("meals", []):
                    previous_day_ids.update(prev_meal.get("component_food_ids", [prev_meal["food_id"]]))

            basa_appearance_count = 0
            for past_day in scheduled_plan:
                for past_meal in past_day.get("meals", []):
                    if "basa" in str(past_meal.get("name") or "").lower():
                        basa_appearance_count += 1

            for sol in sols:
                if checked_count >= MAX_CHECKED: break
                if deadline is not None and time.perf_counter() >= deadline and valid_scored:
                    break
                checked_count += 1
                try:
                    day_meals = self._get_meal_plan_for_solution(
                        sol, constraints, tolerance_multiplier,
                        all_carbs, all_proteins, all_fibers, all_snacks,
                        day_excluded_ids=set(used_food_ids),
                        cached_roles=food_roles_cache,
                        rice_food=domain_context["rice_food"],
                        alternative_carbs=domain_context["alternative_carbs"],
                        clean_proteins=domain_context["clean_proteins"],
                        clean_fibers=domain_context["clean_fibers"],
                    )

                    if dietary_restrictions:
                        day_food_ids = [
                            fid
                            for meal in day_meals
                            for fid in meal.get("component_food_ids", [meal["food_id"]])
                        ]
                        if any(
                            violates_dietary_restrictions(self.food_by_id[fid], dietary_restrictions)
                            for fid in day_food_ids
                        ):
                            continue
                    
                    if not constraints.check_daily_calories(day_meals, tolerance_multiplier): continue
                    if not constraints.check_daily_macros(day_meals, tolerance_multiplier): continue
                    
                    actual_day_cost = sum(m["total_cost_vnd"] for m in day_meals)
                    if not constraints.check_daily_budget([m["total_cost_vnd"] for m in day_meals], tolerance_multiplier): continue

                    base_score = score_meal_plan([{"meals": day_meals}], self.user.get("maximize_nutrients"), self.user.get("minimize_nutrients"))
                    penalty = 0.0

                    target_budget_floor = constraints.budget_vnd_max * 0.60
                    target_budget_ceiling = constraints.budget_vnd_max * 0.88
                    dynamic_weight = max(1.0, 3.5 / tolerance_multiplier)
                    
                    if actual_day_cost < target_budget_floor:
                        penalty += dynamic_weight * (target_budget_floor - actual_day_cost)
                    elif actual_day_cost > target_budget_ceiling:
                        penalty += dynamic_weight * (actual_day_cost - target_budget_ceiling)

                    for m in day_meals:
                        for comp_fid in m.get("component_food_ids", []):
                            f_comp = self.food_by_id[comp_fid]
                            f_name = food_name_low.get(comp_fid, "")
                            
                            # Thưởng đạm thông thường (Trừ gốc cá ra để chấm điểm độc lập phía dưới)
                            if any(k in f_name for k in ["bò", "gà tây", "tôm", "cua", "mực", "hàu", "sò", "hải sản"]):
                                base_score += 100.0
                                
                            # =======================================================================
                            # ĐÃ CẬP NHẬT: THƯỞNG CHO CÁ NẠC NGUYÊN BẢN (CÓ "CÁ" NHƯNG KHÔNG CÓ "CHẢ")
                            # =======================================================================
                            if "cá" in f_name and "chả" not in f_name:
                                base_score += 100.0  # Đẩy mạnh Cá hồi, Cá ngừ, Cá điêu hồng tươi...
                                
                            if any(k in f_name for k in ["cá hồi", "cá ngừ", "thịt bò loại i", "loại i", "loại ii",  "thịt bò loại 1", "thịt bò nạc tươi", "thăn bò"]):
                                base_score += 500.0

                    total_p, total_f, total_c = 0.0, 0.0, 0.0
                    has_clean_chicken = False
                    
                    for m in day_meals:
                        total_p += m["protein"]
                        total_f += m["fat"]
                        total_c += m["carbs"]
                        
                        for comp_fid in m.get("component_food_ids", []):
                            f_comp = self.food_by_id[comp_fid]
                            f_name = food_name_low.get(comp_fid, "")
                            if "clean_protein" in (f_comp.get("tags") or set()) and any(k in f_name for k in ["ức gà", "lườn gà", "gà công nghiệp"]):
                                has_clean_chicken = True
                    
                    if has_clean_chicken:
                        base_score += 800.0

                    total_mass = total_p + total_f + total_c
                    target_p_pct = (self.user.get("macro_ratios") or {}).get("protein")
                    if target_p_pct is None:
                        target_p_pct = constraints.macro_ratios.get("protein", 0.30)
                    target_f_pct = constraints.macro_ratios.get("fat", 0.30)
                    target_c_pct = constraints.macro_ratios.get("carbs", 0.40)
                    if total_mass > 0:
                        actual_p_pct = total_p / total_mass
                        
                        if actual_p_pct < (target_p_pct - 0.02):
                            penalty += 1500.0 * (target_p_pct - actual_p_pct)
                        elif actual_p_pct > (target_p_pct + 0.04):
                            penalty += 2000.0 * (actual_p_pct - target_p_pct)

                    meal_cals = {m["meal_type"]: m["calories"] for m in day_meals}
                    total_actual_cal = sum(meal_cals.values())
                    if total_actual_cal > 0:
                        target_cal = max(float(constraints.daily_calorie_target or 0.0), 1.0)
                        target_protein_g = max(target_cal * float(target_p_pct) / 4.0, 1.0)
                        target_fat_g = max(target_cal * float(target_f_pct) / 9.0, 1.0)
                        target_carbs_g = max(target_cal * float(target_c_pct) / 4.0, 1.0)

                        cal_deviation_pct = abs(total_actual_cal - target_cal) / target_cal
                        protein_deviation_pct = abs(total_p - target_protein_g) / target_protein_g
                        fat_deviation_pct = abs(total_f - target_fat_g) / target_fat_g
                        carbs_deviation_pct = abs(total_c - target_carbs_g) / target_carbs_g
                        penalty += 3200.0 * cal_deviation_pct
                        penalty += 1200.0 * protein_deviation_pct
                        penalty += 350.0 * fat_deviation_pct
                        penalty += 350.0 * carbs_deviation_pct

                        if scheduled_plan:
                            previous_cals = [
                                sum(float(meal.get("calories") or 0.0) for meal in past_day.get("meals", []))
                                for past_day in scheduled_plan
                            ]
                            previous_proteins = [
                                sum(float(meal.get("protein") or 0.0) for meal in past_day.get("meals", []))
                                for past_day in scheduled_plan
                            ]
                            previous_avg_cal = sum(previous_cals) / len(previous_cals)
                            previous_avg_protein = sum(previous_proteins) / len(previous_proteins)
                            penalty += 900.0 * macro_stability_weight * abs(total_actual_cal - previous_avg_cal) / target_cal
                            penalty += 500.0 * macro_stability_weight * abs(total_p - previous_avg_protein) / target_protein_g

                        b_pct = meal_cals.get("breakfast", 0) / total_actual_cal
                        l_pct = meal_cals.get("lunch", 0) / total_actual_cal
                        d_pct = meal_cals.get("dinner", 0) / total_actual_cal
                        
                        if not (0.15 <= b_pct <= 0.35): penalty += 200.0
                        if not (0.25 <= l_pct <= 0.45): penalty += 200.0
                        if not (0.25 <= d_pct <= 0.45): penalty += 200.0

                    cand_ids = []
                    for m in day_meals: cand_ids.extend(m.get("component_food_ids", [m["food_id"]]))
                    global_family_counts = Counter(self._food_repeat_family(fid) for fid in used_food_ids)
                    previous_day_families = {
                        self._food_repeat_family(fid)
                        for fid in previous_day_ids
                    }

                    for fid in cand_ids:
                        name_low = food_name_low.get(fid, "")
                        if any(k in name_low for k in ["cơm tẻ", "cơm trắng", "cơm chín"]): continue

                        count = global_counts[fid]
                        if count == 1: penalty += 40.0 * diversity_penalty_weight
                        elif count >= 2: penalty += 200.0 * diversity_penalty_weight

                        if fid in previous_day_ids:
                            penalty += 200.0 * diversity_penalty_weight

                        if plant_restricted:
                            family = self._food_repeat_family(fid)
                            family_count = global_family_counts[family]
                            if family == "plant_tofu":
                                if family_count >= 2:
                                    penalty += 420.0 * (family_count - 1)
                                if family in previous_day_families:
                                    penalty += 360.0
                            elif family == "egg_quail":
                                penalty += 1400.0 + 900.0 * family_count
                            elif family.startswith("egg_"):
                                if family_count >= 2:
                                    penalty += 500.0 * (family_count - 1)
                                if family in previous_day_families:
                                    penalty += 300.0

                        # Bộ lọc phạt lặp chuỗi "basa"
                        if "basa" in name_low:
                            if basa_appearance_count >= 1:
                                penalty += 600.0 * basa_appearance_count

                    valid_scored.append((base_score - penalty, sol, day_meals))
                except Exception:
                    continue

            # =======================================================================
            # SỬA LỖI TẠI ĐÂY: KHỐI CỨU VÃN KHẨN CẤP (EMERGENCY RECOVERY BLOCK)
            # =======================================================================
            if not valid_scored:
                sols = prob.getSolutionIter()
                emergency_checked = 0
                max_emergency_checked = 25 if deadline is not None and time.perf_counter() >= deadline else 80
                for sol in sols:
                    if emergency_checked >= max_emergency_checked:
                        break
                    emergency_checked += 1
                    try:
                        # THAY ĐỔI QUAN TRỌNG: Truyền used_food_ids thay vì None để khóa chặt chả cá basa lặp
                        day_meals = self._get_meal_plan_for_solution(
                            sol, constraints, tolerance_multiplier, 
                            all_carbs, all_proteins, all_fibers, all_snacks, 
                            day_excluded_ids=set(used_food_ids), # <--- KHÓA CHẶT TRÙNG LẶP KHI HẠ CHUẨN
                            cached_roles=food_roles_cache,
                            rice_food=domain_context["rice_food"],
                            alternative_carbs=domain_context["alternative_carbs"],
                            clean_proteins=domain_context["clean_proteins"],
                            clean_fibers=domain_context["clean_fibers"],
                        )
                        if dietary_restrictions:
                            day_food_ids = [
                                fid
                                for meal in day_meals
                                for fid in meal.get("component_food_ids", [meal["food_id"]])
                            ]
                            if any(
                                violates_dietary_restrictions(self.food_by_id[fid], dietary_restrictions)
                                for fid in day_food_ids
                            ):
                                continue
                        costs = [m["total_cost_vnd"] for m in day_meals]
                        
                        if sum(costs) <= constraints.budget_vnd_max and constraints.check_daily_calories(day_meals, tolerance_multiplier * 1.3):
                            total_p = sum(m["protein"] for m in day_meals)
                            total_m = total_p + sum(m["fat"] for m in day_meals) + sum(m["carbs"] for m in day_meals)
                            
                            if total_m > 0:
                                actual_p_ratio = total_p / total_m
                                user_target_p = (self.user.get("macro_ratios") or {}).get("protein", 0.30)
                                if (user_target_p - 0.04) <= actual_p_ratio <= (user_target_p + 0.05):
                                    valid_scored.append((0, sol, day_meals))
                                    break
                    except Exception: continue

            if not valid_scored:
                return {"feasible": False, "meal_plan": []}

            valid_scored.sort(key=lambda x: x[0], reverse=True)
            best_day = valid_scored[0]
            scheduled_plan.append({"day": day + 1, "meals": best_day[2]})
            
            for m in best_day[2]:
                c_ids = m.get("component_food_ids", [m["food_id"]])
                used_food_ids.extend(c_ids)
                for fid in c_ids:
                    if is_offal_or_blood(self.food_by_id[fid]): offal_blood_count += 1

        final_score = score_meal_plan(scheduled_plan, self.user.get("maximize_nutrients"), self.user.get("minimize_nutrients"))
        return {
            "status": "success",
            "feasible": True,
            "meal_plan": scheduled_plan,
            "score": round(final_score, 2),
            "timed_out": bool(deadline is not None and time.perf_counter() >= deadline),
        }
