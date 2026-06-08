"""Scheduler core utilizing backtracking and automated progressive multi-stage constraint relaxation."""
from __future__ import annotations

import logging
import os
import random
from collections import Counter
from typing import Any, Dict, List, Set

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
        
        self.foods = available_foods or self._load_foods()
        for f in self.foods:
            f["max_serving_g"] = get_max_serving_g(f, self.is_gym)
            
        self.food_by_id = {int(f["food_id"]): f for f in self.foods}
        self._food_roles_cache: Dict[int, str] | None = None
        self._food_name_low_cache: Dict[int, str] | None = None

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

    def _build_domain_context(self, domain_foods: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Precompute domain-level classifications that are reused across CSP attempts."""
        food_roles_cache = self._get_food_roles_cache()
        food_name_low = self._get_food_name_low_cache()

        all_carbs, all_proteins, all_fibers, all_snacks = [], [], [], []
        fallback_carbs, fallback_proteins, fallback_fibers = [], [], []
        breakfast_ids, lunch_ids, dinner_ids, snack_ids = [], [], [], []
        offal_ids: Set[int] = set()
        gym_priority: Dict[int, int] = {}

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
            if role == "MAIN_PROTEIN" and not is_snack_cake:
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

        effective_carbs = all_carbs or fallback_carbs
        effective_proteins = all_proteins or fallback_proteins
        effective_fibers = all_fibers or fallback_fibers
        if not all_snacks:
            all_snacks = domain_foods

        rice_food = next(
            (f for f in effective_carbs if any(k in food_name_low.get(int(f["food_id"]), "") for k in ["cơm tẻ", "cơm trắng", "cơm chín"])),
            None,
        )
        if not rice_food and effective_carbs:
            rice_food = effective_carbs[0]

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
            "fallback_carbs": [int(f["food_id"]) for f in fallback_carbs[:30]],
            "fallback_proteins": [int(f["food_id"]) for f in fallback_proteins[:30]],
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
        constraints = NutrientConstraints(
            daily_calorie_target=float(self.user.get("daily_calorie_target") or 1800.0),
            calorie_tolerance_pct=0.12,
            macro_ratios=self.user.get("macro_ratios"),
            macro_tolerance_pct=0.12,
            allergies=self.user.get("allergies"),
            budget_vnd_max=self.user.get("budget_vnd_max") or 200000.0,
            max_food_occurrences_per_week=3,
        )

        domain_foods = self.foods
        if self.candidate_food_ids is not None:
            domain_foods = [f for f in domain_foods if int(f["food_id"]) in self.candidate_food_ids]
        if constraints.allergies:
            domain_foods = [f for f in domain_foods if constraints.check_allergies([f])]
        dietary_restrictions = self.user.get("dietary_restrictions") or []
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
                        
                return (src_pri, is_clean_p, sim_idx) if self.is_gym else (src_pri, sim_idx)

            domain_foods.sort(key=domain_sort_key)
            domain_foods = domain_foods[:MAX_DOMAIN_SIZE]

        domain_context = self._build_domain_context(domain_foods)

        attempt = 1
        tolerance_multiplier = 1.0

        while attempt <= max_attempts:
            logging.getLogger(__name__).info(
                "CSP Solve Attempt %s/%s (multiplier=%.2f)", attempt, max_attempts, tolerance_multiplier
            )
            result = self._solve(domain_foods, constraints, tolerance_multiplier, domain_context)
            if result["feasible"]:
                result["relaxation_attempts"] = attempt
                return result

            tolerance_multiplier += 0.25
            attempt += 1

        return {
            "status": "infeasible",
            "feasible": False,
            "meal_plan": [],
            "relaxation_attempts": max_attempts,
        }

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

        exclude_snacks = self.user.get("exclude_snacks", False)
        if not exclude_snacks and sol.get("snack"):
            components.append({"slot": "snack", "food": self.food_by_id[sol["snack"]], "role": "snack"})

        p_ratio = constraints.macro_ratios.get("protein", 0.4)
        c_ratio = constraints.macro_ratios.get("carbs", 0.3)
        f_ratio = constraints.macro_ratios.get("fat", 0.3)

        daily_target = float(self.user.get("daily_calorie_target") or 1800.0)
        if daily_target <= 1200.0:
            w_prot_space = [70.0, 100.0, 150.0]
            w_crb_space = [70.0, 100.0, 140.0]
            w_fix_space = [50.0, 75.0, 100.0]
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
                role_protein = (f.get("meal_role") == "MAIN_PROTEIN")
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

        best_w_protein, best_w_carb, best_w_fixed = 150.0, 150.0, 100.0
        min_error = float("inf")
        
        for w_prot in w_prot_space:
            for w_crb in w_crb_space:
                for w_fix in w_fix_space:
                    total_cal, total_p, total_f, total_c = 0.0, 0.0, 0.0, 0.0
                    
                    for f_cal, f_prot, f_fat, f_carb, w_type, max_w in preclassified_components:
                        if w_type == "fix": w = w_fix
                        elif w_type == "crb": w = w_crb
                        else: w = w_prot
                        
                        w = min(w, max_w)
                        factor = w / 100.0
                        total_cal += f_cal * factor
                        total_p += f_prot * factor
                        total_f += f_fat * factor
                        total_c += f_carb * factor

                    cal_error = abs(total_cal - constraints.daily_calorie_target) / constraints.daily_calorie_target
                    
                    # Add heavy penalty if total calories are outside allowed bounds
                    tolerance = constraints.daily_calorie_target * constraints.calorie_tolerance_pct * tolerance_multiplier
                    min_cal = constraints.daily_calorie_target - tolerance
                    max_cal = constraints.daily_calorie_target + tolerance
                    if not (min_cal <= total_cal <= max_cal):
                        cal_penalty = 1000.0
                    else:
                        cal_penalty = 0.0

                    total_mass = total_p + total_f + total_c
                    if total_mass > 0:
                        macro_error = (
                            abs((total_p / total_mass) - p_ratio) * 6.0 +  
                            abs((total_f / total_mass) - f_ratio) * 1.5 +
                            abs((total_c / total_mass) - c_ratio) * 1.5
                        )
                    else: macro_error = 1.0
                        
                    error = cal_error + macro_error + cal_penalty
                    if error < min_error:
                        min_error = error
                        best_w_protein, best_w_carb, best_w_fixed = w_prot, w_crb, w_fix

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
                    elif role in ["protein", "core"] and (is_standalone_main_dish(f) or fast_classify(f) == "MAIN_PROTEIN"): w = best_w_protein
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
    ) -> Dict[str, Any]:
        """Core sequential CSP engine with optimized pricing heuristics."""
        
        food_roles_cache = domain_context["roles"]
        food_name_low = domain_context["names"]
        all_carbs = domain_context["all_carbs"]
        all_proteins = domain_context["all_proteins"]
        all_fibers = domain_context["all_fibers"]
        all_snacks = domain_context["all_snacks"]

        exclude_snacks = self.user.get("exclude_snacks", False)
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
                if global_counts[fid] >= 3 and not ("cơm" in name_vi or "com" in name_vi):
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

            random.shuffle(breakfast_candidates)

            prob = Problem()
            prob.addVariable("breakfast", breakfast_candidates[:50])
            prob.addVariable("lunch", lunch_candidates[:150])
            if not exclude_snacks:
                snack_candidates = snack_foods[:50]
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
            MAX_CHECKED = 200
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
                    if total_mass > 0:
                        actual_p_pct = total_p / total_mass
                        target_p_pct = (self.user.get("macro_ratios") or {}).get("protein")
                        if target_p_pct is None:
                            target_p_pct = constraints.macro_ratios.get("protein", 0.30)
                        
                        if actual_p_pct < (target_p_pct - 0.02):
                            penalty += 1500.0 * (target_p_pct - actual_p_pct)
                        elif actual_p_pct > (target_p_pct + 0.04):
                            penalty += 2000.0 * (actual_p_pct - target_p_pct)

                    meal_cals = {m["meal_type"]: m["calories"] for m in day_meals}
                    total_actual_cal = sum(meal_cals.values())
                    if total_actual_cal > 0:
                        b_pct = meal_cals.get("breakfast", 0) / total_actual_cal
                        l_pct = meal_cals.get("lunch", 0) / total_actual_cal
                        d_pct = meal_cals.get("dinner", 0) / total_actual_cal
                        
                        if not (0.15 <= b_pct <= 0.35): penalty += 200.0
                        if not (0.25 <= l_pct <= 0.45): penalty += 200.0
                        if not (0.25 <= d_pct <= 0.45): penalty += 200.0

                    cand_ids = []
                    for m in day_meals: cand_ids.extend(m.get("component_food_ids", [m["food_id"]]))

                    for fid in cand_ids:
                        name_low = food_name_low.get(fid, "")
                        if any(k in name_low for k in ["cơm tẻ", "cơm trắng", "cơm chín"]): continue

                        count = global_counts[fid]
                        if count == 1: penalty += 40.0
                        elif count >= 2: penalty += 200.0

                        if fid in previous_day_ids:
                            penalty += 200.0

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
                for sol in sols:
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
        }
