"""KNN Recommendation System for Pre-filtering Foods in NutriAdvisor."""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Set

from csp.classification import (
    classify_food,
    clean_category,
    get_dynamic_tags,
    is_standalone_main_dish,
)


class KNNFoodRecommender:
    """Pre-filter foods for CSP using nutrient-vector similarity."""

    def __init__(self) -> None:
        self.feature_matrix: np.ndarray | None = None
        self._feature_unit_matrix: np.ndarray | None = None
        self._macro_unit_matrix: np.ndarray | None = None
        self.food_metadata: list[dict] | None = None
        self._food_index_by_id: dict[int, int] = {}
        self._replacement_profile_cache: dict[int, dict[str, Any]] = {}
        self._similar_cache: dict[tuple[int, int, tuple[int, ...]], list[dict]] = {}
        self.min_values: dict[str, float] = {}
        self.max_values: dict[str, float] = {}

    def fit(self, feature_matrix: np.ndarray, food_metadata: list[dict], raw_df: pd.DataFrame | None = None) -> None:
        """Fit KNN on normalized nutrient vectors and extract min/max for normalization."""
        self.feature_matrix = np.asarray(feature_matrix, dtype=np.float32)
        self.food_metadata = food_metadata
        self._food_index_by_id = {
            int(food["food_id"]): idx
            for idx, food in enumerate(food_metadata)
        }
        self._replacement_profile_cache = {}
        self._similar_cache = {}

        full_norms = np.linalg.norm(self.feature_matrix, axis=1, keepdims=True)
        full_norms_safe = np.where(full_norms == 0.0, 1.0, full_norms)
        self._feature_unit_matrix = self.feature_matrix / full_norms_safe

        macro_matrix = self.feature_matrix[:, :4]
        macro_norms = np.linalg.norm(macro_matrix, axis=1, keepdims=True)
        macro_norms_safe = np.where(macro_norms == 0.0, 1.0, macro_norms)
        self._macro_unit_matrix = macro_matrix / macro_norms_safe

        try:
            from backend.ml.feature_store.extract_features import NUTRIENT_COLUMNS
        except ModuleNotFoundError:
            from ml.feature_store.extract_features import NUTRIENT_COLUMNS

        # Set default min/max fallbacks for safety
        defaults = {
            "energy_kcal": (0.0, 900.0),
            "protein_g": (0.0, 100.0),
            "fat_g": (0.0, 100.0),
            "carbs_g": (0.0, 100.0),
        }

        # Extract min and max values if raw DataFrame is provided
        if raw_df is not None:
            for col in NUTRIENT_COLUMNS:
                if col in raw_df.columns:
                    vals = pd.to_numeric(raw_df[col], errors="coerce").fillna(0.0).astype(float)
                    self.min_values[col] = float(vals.min())
                    self.max_values[col] = float(vals.max())

        # Ensure we have min/max for all columns
        for col in NUTRIENT_COLUMNS:
            if col not in self.min_values:
                min_val, max_val = defaults.get(col, (0.0, 1.0))
                self.min_values[col] = min_val
                self.max_values[col] = max_val

    def _normalize_query_vector(self, query_dict: dict[str, float], keys: list[str]) -> np.ndarray:
        """Normalize query nutrients to [0, 1] using min/max values."""
        norm_values = []
        for col in keys:
            val = float(query_dict.get(col, 0.0))
            min_val = self.min_values.get(col, 0.0)
            max_val = self.max_values.get(col, 1.0)
            if max_val > min_val:
                norm_val = (val - min_val) / (max_val - min_val)
            else:
                norm_val = 0.0
            norm_values.append(norm_val)
        return np.asarray(norm_values, dtype=np.float32)

    @staticmethod
    def estimate_daily_portion_units(user_profile: dict[str, Any]) -> float:
        """Estimate total daily 100g food units for mapping daily targets to food vectors."""
        daily_cal = float(user_profile.get("daily_calorie_target") or 2000.0)
        restrictions = {
            str(item).strip().lower()
            for item in (user_profile.get("dietary_restrictions") or [])
            if str(item).strip()
        }
        ratios = user_profile.get("macro_ratios") or {}
        protein_ratio = float(ratios.get("protein", 0.30))
        exclude_snacks = bool(user_profile.get("exclude_snacks", False))
        snack_threshold = float(user_profile.get("enable_snack_from_kcal") or 2400.0)

        if daily_cal <= 1400.0:
            units = 12.5
        elif daily_cal <= 1800.0:
            units = 14.0
        elif daily_cal <= 2400.0:
            units = 15.5
        elif daily_cal <= 3000.0:
            units = 18.0
        else:
            units = 20.5

        if {"vegetarian", "vegan"}.intersection(restrictions):
            units += 2.0
        elif restrictions:
            units += 0.75

        if daily_cal >= snack_threshold and not exclude_snacks:
            units += 1.0

        if protein_ratio >= 0.35:
            units -= 1.0
        elif protein_ratio <= 0.22:
            units += 0.75

        return max(11.0, min(units, 23.0))

    @staticmethod
    def _food_value(food: dict[str, Any], *keys: str) -> float:
        for key in keys:
            value = food.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return 0.0

    @staticmethod
    def _ensure_tags(food: dict[str, Any]) -> set[str]:
        tags = food.get("tags") or set()
        if isinstance(tags, list):
            tags = set(tags)
        if not tags:
            tags = get_dynamic_tags(food)
            food["tags"] = tags
        return tags

    @staticmethod
    def _food_name(food: dict[str, Any]) -> str:
        return str(food.get("name_vi") or food.get("canonical_name_en") or food.get("name_en") or "").lower()

    @staticmethod
    def _classify_replacement_kind(
        food: dict[str, Any],
        tags: set[str],
        name: str,
        category: str,
        role: str,
    ) -> str:
        noodle_keywords = [
            "bún", "bun", "phở", "pho", "miến", "mien", "mỳ", "mì", "my ",
            "cháo", "chao", "bánh canh", "banh canh", "hủ tiếu", "hu tieu",
            "bánh đa", "banh da",
        ]
        main_keywords = noodle_keywords + [
            "xôi", "xoi", "bánh mì", "banh mi", "bánh cuốn", "banh cuon",
            "cơm rang", "com rang", "cơm tấm", "com tam",
        ]

        if is_standalone_main_dish(food) or any(k in name for k in main_keywords) or "mon_nuoc" in category:
            if any(k in name for k in noodle_keywords) or "mon_nuoc" in category:
                return "main_bowl"
            return "main_dish"
        if "is_dessert_snack" in tags:
            return "snack"
        if role in {"MAIN_PROTEIN", "PLANT_PROTEIN"}:
            return "protein"
        if role == "STAPLE_CARB":
            return "carb"
        if role == "FIBER_SIDE":
            return "fiber"
        return "accessory"

    def _replacement_profile_for_index(self, idx: int) -> dict[str, Any]:
        cached = self._replacement_profile_cache.get(idx)
        if cached is not None:
            return cached

        food = self.food_metadata[idx]
        tags = self._ensure_tags(food)
        name = self._food_name(food)
        category = clean_category(food.get("category"))
        role = classify_food(food)
        profile = {
            "idx": idx,
            "food_id": int(food["food_id"]),
            "kind": self._classify_replacement_kind(food, tags, name, category, role),
            "role": role,
            "tags": tags,
            "category": category,
            "calories": self._food_value(food, "calories", "energy_kcal"),
        }
        self._replacement_profile_cache[idx] = profile
        return profile

    def _replacement_kind(self, food: dict[str, Any]) -> str:
        tags = self._ensure_tags(food)
        name = self._food_name(food)
        category = clean_category(food.get("category"))
        role = classify_food(food)
        return self._classify_replacement_kind(food, tags, name, category, role)

    @staticmethod
    def _is_compatible_replacement(query: dict[str, Any], candidate: dict[str, Any]) -> bool:
        query_kind = query["kind"]
        candidate_kind = candidate["kind"]
        candidate_role = candidate["role"]
        candidate_tags = candidate["tags"]

        if candidate_kind == "accessory":
            return False
        if candidate_role == "ACCESSORY_CONDIMENT" and candidate_kind not in {"main_bowl", "main_dish"}:
            return False
        if query_kind not in {"snack", "accessory"} and "is_dessert_snack" in candidate_tags:
            return False

        query_cal = float(query["calories"])
        candidate_cal = float(candidate["calories"])
        if query_cal > 0.0 and candidate_cal > 0.0:
            if candidate_cal < query_cal * 0.45 or candidate_cal > query_cal * 2.75:
                return False

        if query_kind == "main_bowl":
            return candidate_kind == "main_bowl"
        if query_kind == "main_dish":
            return candidate_kind in {"main_dish", "main_bowl"}
        if query_kind == "protein":
            return candidate_kind == "protein"
        if query_kind == "carb":
            return candidate_kind in {"carb", "main_bowl", "main_dish"}
        if query_kind == "fiber":
            return candidate_kind == "fiber"
        if query_kind == "snack":
            return candidate_kind == "snack"
        return candidate_kind not in {"accessory"}

    @staticmethod
    def _replacement_penalty(query: dict[str, Any], candidate: dict[str, Any]) -> float:
        query_kind = query["kind"]
        candidate_kind = candidate["kind"]
        penalty = 0.0
        if query_kind != candidate_kind:
            penalty += 0.08

        query_cat = query["category"]
        cand_cat = candidate["category"]
        if query_cat and cand_cat and query_cat != cand_cat:
            penalty += 0.03

        query_cal = float(query["calories"])
        cand_cal = float(candidate["calories"])
        if query_cal > 0.0 and cand_cal > 0.0:
            penalty += min(abs(cand_cal - query_cal) / max(query_cal, 1.0), 2.0) * 0.04
        return penalty

    def recommend_for_profile(self, user_profile: dict[str, Any], n: int = 120) -> list[int]:
        """Create a candidate pool for CSP based on user's target calorie and macro ratios.

        1. Tính target nutrient vector từ user_profile.
        2. Cosine distance tìm top-N foods gần nhất.
        3. Đảm bảo đa dạng: stratified sampling theo role.
        4. Lọc dị ứng trước khi trả về.
        """
        if self.feature_matrix is None or self.food_metadata is None:
            raise RuntimeError("KNNRecommender is not fitted yet. Call fit() first.")

        # 1. Target daily nutrients
        daily_cal = float(user_profile.get("daily_calorie_target") or 2000.0)
        ratios = user_profile.get("macro_ratios") or {"protein": 0.3, "fat": 0.3, "carbs": 0.4}

        target_p_g = daily_cal * ratios.get("protein", 0.3) / 4.0
        target_f_g = daily_cal * ratios.get("fat", 0.3) / 9.0
        target_c_g = daily_cal * ratios.get("carbs", 0.4) / 4.0

        # Scale daily targets down to a realistic daily count of 100g food units.
        portion_divisor = self.estimate_daily_portion_units(user_profile)
        target_dict = {
            "energy_kcal": daily_cal / portion_divisor,
            "protein_g": target_p_g / portion_divisor,
            "fat_g": target_f_g / portion_divisor,
            "carbs_g": target_c_g / portion_divisor,
        }

        try:
            from backend.ml.feature_store.extract_features import NUTRIENT_COLUMNS
        except ModuleNotFoundError:
            from ml.feature_store.extract_features import NUTRIENT_COLUMNS
        macro_keys = list(NUTRIENT_COLUMNS[:4])
        query_vector = self._normalize_query_vector(target_dict, macro_keys)

        # 2. Compute cosine similarity on 4D submatrix (energy, protein, fat, carbs)
        q_norm = np.linalg.norm(query_vector)
        if q_norm == 0:
            q_unit = query_vector
        else:
            q_unit = query_vector / q_norm

        similarities = np.dot(self._macro_unit_matrix, q_unit)
        distances = 1.0 - similarities

        sorted_indices = np.argsort(distances)

        # 3. Filter allergies and dietary restrictions
        from csp.constraints import NutrientConstraints
        from csp.classification import violates_dietary_restrictions
        constraints = NutrientConstraints(
            daily_calorie_target=daily_cal,
            macro_ratios=ratios,
            allergies=user_profile.get("allergies"),
        )
        dietary_restrictions = user_profile.get("dietary_restrictions") or []

        has_allergies = bool(user_profile.get("allergies"))
        if not has_allergies and not dietary_restrictions:
            filtered_indices = sorted_indices.tolist()
        else:
            filtered_indices = []
            for idx in sorted_indices:
                food = self.food_metadata[idx]
                if "tags" not in food:
                    from csp.scheduler import get_dynamic_tags
                    food["tags"] = get_dynamic_tags(food)
                if has_allergies and not constraints.check_allergies([food]):
                    continue
                if dietary_restrictions and violates_dietary_restrictions(food, dietary_restrictions):
                    continue
                filtered_indices.append(idx)

        # 4. Stratified selection
        dietary_restrictions = {
            str(r).strip().lower()
            for r in (user_profile.get("dietary_restrictions") or [])
            if str(r).strip()
        }
        snack_threshold = float(user_profile.get("enable_snack_from_kcal") or 2400.0)
        exclude_snacks = bool(user_profile.get("exclude_snacks", False))
        if daily_cal >= 1600.0 and {"vegetarian", "vegan"}.intersection(dietary_restrictions):
            exclude_snacks = False
        elif daily_cal >= 2200.0 and dietary_restrictions:
            exclude_snacks = False
        elif daily_cal >= snack_threshold:
            exclude_snacks = False

        def is_snack_food(f: dict[str, Any]) -> bool:
            tags = f.get("tags") or set()
            from csp.scheduler import clean_category
            cat_clean = clean_category(f.get("category"))
            return "is_dessert_snack" in tags or any(k in cat_clean for k in ("do_an_vat", "trang_mieng", "banh_keo", "banh_ngot"))

        proteins = []
        carbs = []
        fibers = []
        snacks = []
        others = []

        from csp.scheduler import get_food_role

        for idx in filtered_indices:
            food = self.food_metadata[idx]
            is_p, is_c, is_f = get_food_role(food)
            is_s = is_snack_food(food)

            if is_s:
                snacks.append(idx)
            elif is_p:
                proteins.append(idx)
            elif is_c:
                carbs.append(idx)
            elif is_f:
                fibers.append(idx)
            else:
                others.append(idx)

        if exclude_snacks:
            snacks = []

        # Gym profile check
        is_gym_profile = (
            float(user_profile.get("daily_calorie_target") or 0.0) >= 2800.0
            or str(user_profile.get("goal") or "").lower() == "gym"
            or "gym" in str(user_profile.get("user_message") or "").lower()
            or (user_profile.get("macro_ratios") or {}).get("protein", 0.0) >= 0.25
        )

        if is_gym_profile:
            from csp.classification import is_clean_protein_gym
            def protein_sort_key(idx):
                food = self.food_metadata[idx]
                tags = food.get("tags") or set()
                name_low = str(food.get("name_vi") or "").lower()
                is_clean = "clean_protein" in tags or is_clean_protein_gym(food)
                if is_clean:
                    if any(k in name_low for k in ["ức gà", "lườn gà", "gà công nghiệp", "thăn bò", "bắp bò", "bò, loại i", "bò, lưng, nạc", "thăn lợn", "thăn heo", "lợn, loại i", "heo, loại i", "cá hồi", "cá ngừ", "cá quả", "cá chép", "cá trắm", "cá basa", "cá chim", "cá điêu hồng"]):
                        return 0
                    return 1
                return 2
            proteins.sort(key=protein_sort_key)


        # Target counts for diversity

        target_protein = int(n * 0.35)
        target_carb = int(n * 0.35)
        target_fiber = int(n * 0.20)
        target_snack = 0 if exclude_snacks else int(n * 0.10)

        selected_set: Set[int] = set()
        selected_list: List[int] = []

        def add_candidates(pool: list[int], target_count: int) -> None:
            added = 0
            for idx in pool:
                if added >= target_count:
                    break
                fid = int(self.food_metadata[idx]["food_id"])
                if fid not in selected_set:
                    selected_set.add(fid)
                    selected_list.append(fid)
                    added += 1

        add_candidates(proteins, target_protein)
        add_candidates(carbs, target_carb)
        add_candidates(fibers, target_fiber)
        if not exclude_snacks:
            add_candidates(snacks, target_snack)

        # Fill remaining slots up to n
        for idx in filtered_indices:
            if len(selected_list) >= n:
                break
            food = self.food_metadata[idx]
            fid = int(food["food_id"])
            if fid not in selected_set:
                if exclude_snacks and is_snack_food(food):
                    continue
                selected_set.add(fid)
                selected_list.append(fid)

        return selected_list

    def recommend_similar(self, food_id: int, n: int = 5, exclude: list[int] | None = None) -> list[dict]:
        """Gợi ý thay thế: tìm món tương tự về dinh dưỡng và tương thích vai trò bữa ăn."""
        if self.feature_matrix is None or self._feature_unit_matrix is None or self.food_metadata is None:
            raise RuntimeError("KNNRecommender is not fitted yet. Call fit() first.")

        if exclude is None:
            exclude = []
        exclude_set = {int(fid) for fid in exclude}
        cache_key = (int(food_id), int(n), tuple(sorted(exclude_set)))
        cached = self._similar_cache.get(cache_key)
        if cached is not None:
            return [item.copy() for item in cached]

        query_idx = self._food_index_by_id.get(int(food_id))
        if query_idx is None:
            return []

        query_profile = self._replacement_profile_for_index(query_idx)
        query_vector = self.feature_matrix[query_idx]
        q_norm = np.linalg.norm(query_vector)
        if q_norm == 0:
            q_unit = query_vector
        else:
            q_unit = query_vector / q_norm

        similarities = np.dot(self._feature_unit_matrix, q_unit)
        distances = 1.0 - similarities

        total = len(self.food_metadata)
        windows = []
        for window in (max(n * 20, 80), max(n * 40, 160), total):
            window = min(max(window, n), total)
            if window not in windows:
                windows.append(window)

        scored_indices = []
        for window in windows:
            if window >= total:
                candidate_indices = np.argsort(distances)
            else:
                candidate_indices = np.argpartition(distances, window - 1)[:window]
                candidate_indices = candidate_indices[np.argsort(distances[candidate_indices])]

            scored_indices = []
            for idx in candidate_indices:
                idx = int(idx)
                candidate_profile = self._replacement_profile_for_index(idx)
                fid = candidate_profile["food_id"]
                if fid == int(food_id) or fid in exclude_set:
                    continue
                if not self._is_compatible_replacement(query_profile, candidate_profile):
                    continue
                score = float(distances[idx]) + self._replacement_penalty(query_profile, candidate_profile)
                scored_indices.append((score, idx))
            scored_indices.sort(key=lambda item: item[0])
            if len(scored_indices) >= n or window >= total:
                break

        recommendations = []
        for score, idx in scored_indices:
            food = self.food_metadata[idx]
            fid = int(food["food_id"])

            recommendations.append({
                "food_id": fid,
                "canonical_key": food.get("canonical_key", ""),
                "name_en": food.get("canonical_name_en", ""),
                "name_vi": food.get("name_vi", ""),
                "calories": float(food.get("calories") or food.get("energy_kcal") or 0.0),
                "protein": float(food.get("protein") or food.get("protein_g") or 0.0),
                "fat": float(food.get("fat") or food.get("fat_g") or 0.0),
                "carbs": float(food.get("carbs") or food.get("carbs_g") or 0.0),
                "cost_vnd_100g": float(food.get("cost_vnd_100g") or food.get("price_100g") or 0.0),
                "match_score": float(max(0.0, min(1.0, 1.0 - score))),
            })

            if len(recommendations) >= n:
                break

        self._similar_cache[cache_key] = [item.copy() for item in recommendations]
        return recommendations

    def recommend_complementary(self, current_food_ids: list[int], target_profile: dict, n: int = 10) -> list[dict]:
        """Gợi ý bổ sung: tìm foods bù đắp thiếu hụt macro."""
        if self.feature_matrix is None or self.food_metadata is None:
            raise RuntimeError("KNNRecommender is not fitted yet. Call fit() first.")

        # 1. Compute current nutrient sum
        current_cal = 0.0
        current_p = 0.0
        current_f = 0.0
        current_c = 0.0

        food_by_id = {int(f["food_id"]): (f, self.feature_matrix[i]) for i, f in enumerate(self.food_metadata)}

        for fid in current_food_ids:
            if fid in food_by_id:
                food, vec = food_by_id[fid]
                cal = float(food.get("calories") or food.get("energy_kcal") or 0.0)
                p = float(food.get("protein") or food.get("protein_g") or 0.0)
                f = float(food.get("fat") or food.get("fat_g") or 0.0)
                c = float(food.get("carbs") or food.get("carbs_g") or 0.0)

                # Fallback to normalized vectors if raw values are missing
                if cal == 0.0 and p == 0.0 and f == 0.0 and c == 0.0:
                    cal = vec[0] * (self.max_values["energy_kcal"] - self.min_values["energy_kcal"]) + self.min_values["energy_kcal"]
                    p = vec[1] * (self.max_values["protein_g"] - self.min_values["protein_g"]) + self.min_values["protein_g"]
                    f = vec[2] * (self.max_values["fat_g"] - self.min_values["fat_g"]) + self.min_values["fat_g"]
                    c = vec[3] * (self.max_values["carbs_g"] - self.min_values["carbs_g"]) + self.min_values["carbs_g"]

                current_cal += cal
                current_p += p
                current_f += f
                current_c += c

        # 2. Get target nutrients
        daily_cal = float(target_profile.get("daily_calorie_target") or 2000.0)
        ratios = target_profile.get("macro_ratios") or {"protein": 0.3, "fat": 0.3, "carbs": 0.4}
        target_p = daily_cal * ratios.get("protein", 0.3) / 4.0
        target_f = daily_cal * ratios.get("fat", 0.3) / 9.0
        target_c = daily_cal * ratios.get("carbs", 0.4) / 4.0

        # 3. Compute deficit
        def_cal = max(0.0, daily_cal - current_cal)
        def_p = max(0.0, target_p - current_p)
        def_f = max(0.0, target_f - current_f)
        def_c = max(0.0, target_c - current_c)

        if def_cal == 0.0 and def_p == 0.0 and def_f == 0.0 and def_c == 0.0:
            # No deficit, search for foods general to profile
            recs = self.recommend_for_profile(target_profile, n)
            results = []
            for fid in recs:
                if fid in food_by_id:
                    food, _ = food_by_id[fid]
                    results.append({
                        "food_id": fid,
                        "canonical_key": food.get("canonical_key", ""),
                        "name_en": food.get("canonical_name_en", ""),
                        "name_vi": food.get("name_vi", ""),
                        "match_score": 1.0,
                    })
            return results

        deficit_dict = {
            "energy_kcal": def_cal,
            "protein_g": def_p,
            "fat_g": def_f,
            "carbs_g": def_c,
        }

        # 4. Query with the deficit vector
        try:
            from backend.ml.feature_store.extract_features import NUTRIENT_COLUMNS
        except ModuleNotFoundError:
            from ml.feature_store.extract_features import NUTRIENT_COLUMNS
        macro_keys = list(NUTRIENT_COLUMNS[:4])
        query_vector = self._normalize_query_vector(deficit_dict, macro_keys)

        sub_matrix = self.feature_matrix[:, :4]
        q_norm = np.linalg.norm(query_vector)
        if q_norm == 0:
            q_unit = query_vector
        else:
            q_unit = query_vector / q_norm

        m_norms = np.linalg.norm(sub_matrix, axis=1)
        m_norms_safe = np.where(m_norms == 0.0, 1.0, m_norms)
        similarities = np.dot(sub_matrix, q_unit) / m_norms_safe
        similarities = np.where(m_norms == 0.0, 0.0, similarities)
        distances = 1.0 - similarities

        sorted_indices = np.argsort(distances)

        recommendations = []
        for idx in sorted_indices:
            food = self.food_metadata[idx]
            fid = int(food["food_id"])
            if fid in current_food_ids:
                continue

            recommendations.append({
                "food_id": fid,
                "canonical_key": food.get("canonical_key", ""),
                "name_en": food.get("canonical_name_en", ""),
                "name_vi": food.get("name_vi", ""),
                "calories": float(food.get("calories") or food.get("energy_kcal") or 0.0),
                "protein": float(food.get("protein") or food.get("protein_g") or 0.0),
                "fat": float(food.get("fat") or food.get("fat_g") or 0.0),
                "carbs": float(food.get("carbs") or food.get("carbs_g") or 0.0),
                "cost_vnd_100g": float(food.get("cost_vnd_100g") or food.get("price_100g") or 0.0),
                "match_score": float(1.0 - distances[idx]),
            })

            if len(recommendations) >= n:
                break

        return recommendations
