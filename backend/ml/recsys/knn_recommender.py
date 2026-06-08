"""KNN Recommendation System for Pre-filtering Foods in NutriAdvisor."""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Set


class KNNFoodRecommender:
    """Pre-filter foods for CSP using nutrient-vector similarity."""

    def __init__(self) -> None:
        self.feature_matrix: np.ndarray | None = None
        self.food_metadata: list[dict] | None = None
        self.min_values: dict[str, float] = {}
        self.max_values: dict[str, float] = {}

    def fit(self, feature_matrix: np.ndarray, food_metadata: list[dict], raw_df: pd.DataFrame | None = None) -> None:
        """Fit KNN on normalized nutrient vectors and extract min/max for normalization."""
        self.feature_matrix = feature_matrix
        self.food_metadata = food_metadata

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

        # Scale down to a standard 100g portion reference
        portion_divisor = 15.0
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

        # 3. Filter allergies
        from csp.constraints import NutrientConstraints
        constraints = NutrientConstraints(
            daily_calorie_target=daily_cal,
            macro_ratios=ratios,
            allergies=user_profile.get("allergies"),
        )

        filtered_indices = []
        for idx in sorted_indices:
            food = self.food_metadata[idx]
            if "tags" not in food:
                from csp.scheduler import get_dynamic_tags
                food["tags"] = get_dynamic_tags(food)
            if constraints.check_allergies([food]):
                filtered_indices.append(idx)

        # 4. Stratified selection
        exclude_snacks = user_profile.get("exclude_snacks", False)

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
        """Gợi ý thay thế: tìm N foods tương tự về dinh dưỡng (14D)."""
        if self.feature_matrix is None or self.food_metadata is None:
            raise RuntimeError("KNNRecommender is not fitted yet. Call fit() first.")

        if exclude is None:
            exclude = []

        # Find query index
        query_idx = None
        for idx, food in enumerate(self.food_metadata):
            if int(food["food_id"]) == int(food_id):
                query_idx = idx
                break

        if query_idx is None:
            return []

        query_vector = self.feature_matrix[query_idx]
        q_norm = np.linalg.norm(query_vector)
        if q_norm == 0:
            q_unit = query_vector
        else:
            q_unit = query_vector / q_norm

        m_norms = np.linalg.norm(self.feature_matrix, axis=1)
        m_norms_safe = np.where(m_norms == 0.0, 1.0, m_norms)

        similarities = np.dot(self.feature_matrix, q_unit) / m_norms_safe
        similarities = np.where(m_norms == 0.0, 0.0, similarities)
        distances = 1.0 - similarities

        sorted_indices = np.argsort(distances)

        recommendations = []
        for idx in sorted_indices:
            food = self.food_metadata[idx]
            fid = int(food["food_id"])
            if fid == int(food_id) or fid in exclude:
                continue

            recommendations.append({
                "food_id": fid,
                "canonical_key": food.get("canonical_key", ""),
                "name_en": food.get("canonical_name_en", ""),
                "name_vi": food.get("name_vi", ""),
                "match_score": float(1.0 - distances[idx]),
            })

            if len(recommendations) >= n:
                break

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
                "match_score": float(1.0 - distances[idx]),
            })

            if len(recommendations) >= n:
                break

        return recommendations
