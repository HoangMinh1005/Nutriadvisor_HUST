"""Pipeline orchestrator for NutriAdvisor HUST meal planner - Upgraded for High-Protein Domain Compliance."""

from __future__ import annotations

import os
from typing import Any, Dict, List

try:
    from backend.ml.feature_store.extract_features import FeatureStore
    from backend.ml.recsys.knn_recommender import KNNFoodRecommender
except ModuleNotFoundError:
    from ml.feature_store.extract_features import FeatureStore
    from ml.recsys.knn_recommender import KNNFoodRecommender
from csp.scheduler import MealScheduler


class MealPlanPipeline:
    """End-to-end pipeline: NLP → KNN → CSP → Meal Plan."""

    def __init__(self, db_url: str | None = None, cache_dir: str | None = None) -> None:
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.feature_store = FeatureStore(db_url=self.db_url, cache_dir=cache_dir)
        self.knn = KNNFoodRecommender()
        self._fitted = False

    def initialize(self, rebuild: bool = False) -> None:
        """Load feature store and fit the KNN model, prioritizing the cached snapshot."""
        snapshot = None
        if not rebuild:
            try:
                snapshot = self.feature_store.load_cached_features("food_feature_snapshot")
            except Exception:
                snapshot = None

        if snapshot is None:
            snapshot = self.feature_store.build_snapshot()

        self.knn.fit(
            feature_matrix=snapshot["matrix"],
            food_metadata=snapshot["metadata"],
            raw_df=snapshot.get("raw"),
        )
        self._fitted = True

    def generate_meal_plan(self, user_profile: dict[str, Any]) -> dict[str, Any]:
        """Main orchestrator method:

        1. KNN finds a rich set of top candidate foods to ensure cross-functional nutrition variety.
        2. Retrieves clean database specifications from PostgreSQL via FeatureStore.
        3. CSP schedules a structurally valid, cost-controlled 7-day meal plan.
        """
        if not self._fitted:
            self.initialize()

        # NÂNG CẤP CHÍ MẠNG: Tăng kích thước không gian ứng viên từ n=120 lên n=400.
        # Ràng buộc cắt nhánh sớm (inline constraints) trong scheduler.py mới chạy rất nhanh, 
        # nên việc nâng n lên 400 sẽ đảm bảo cung cấp đủ pool Cơm, Bún, Thịt nạc, Rau xanh chuẩn 
        # cho CSP phối hợp mà không gây treo hay chậm hệ thống.
        candidate_ids = self.knn.recommend_for_profile(user_profile, n=400)

        # 2. Retrieve details for candidate foods from PostgreSQL
        candidate_foods = self.feature_store.get_food_details(candidate_ids)

        # 3. Solve using CSP MealScheduler
        scheduler = MealScheduler(
            user_profile=user_profile,
            available_foods=candidate_foods,
            db_url=self.db_url,
            candidate_food_ids=candidate_ids,
        )

        return scheduler.solve_with_relaxation()

    def find_replacement(self, food_id: int, user_profile: dict[str, Any], n: int = 5) -> list[dict[str, Any]]:
        """Find nutrient-similar alternative foods."""
        if not self._fitted:
            self.initialize()

        # Find other foods matching target profile parameters or general similarity
        exclude = [food_id]
        return self.knn.recommend_similar(food_id=food_id, n=n, exclude=exclude)