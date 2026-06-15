"""Unit tests for K-Means user segmentation."""
import pytest
import numpy as np
from backend.ml.clustering import (
    UserProfile,
    ClusterAssignment,
    UserSegmentation,
    get_segment_names,
    MENU_TEMPLATES,
    get_segment_policy,
    apply_segment_policy_to_csp_profile,
)


class TestUserProfile:
    """Test UserProfile dataclass."""
    
    def test_user_profile_creation(self):
        """Test creating a user profile."""
        user = UserProfile(
            user_id=1,
            age=30,
            weight_kg=70,
            height_cm=170,
            daily_calorie_target=2000,
            health_goal="maintenance",
            allergies=["peanut"],
            dietary_restrictions=["vegetarian"],
            physical_activity_level="Moderately Active",
            budget_vnd_max=80000,
            maintenance_calories=2200,
            daily_caloric_surplus=-200,
        )
        assert user.user_id == 1
        assert user.age == 30
        assert len(user.allergies) == 1
        assert user.dietary_restrictions == ["vegetarian"]
    
    def test_bmi_calculation(self):
        """Test BMI calculation from weight and height."""
        user = UserProfile(
            user_id=1,
            age=30,
            weight_kg=70,
            height_cm=170,
            daily_calorie_target=2000,
            health_goal="maintenance"
        )
        # BMI = 70 / (1.7 * 1.7) = 24.22
        assert abs(user.bmi - 24.22) < 0.1
    
    def test_user_profile_allergies_empty_default(self):
        """Test allergies default to empty list."""
        user = UserProfile(
            user_id=1,
            age=30,
            weight_kg=70,
            height_cm=170,
            daily_calorie_target=2000,
            health_goal="maintenance"
        )
        assert user.allergies == []


class TestUserSegmentation:
    """Test UserSegmentation clustering."""
    
    @pytest.fixture
    def sample_users(self):
        """Create sample users for testing."""
        users = [
            UserProfile(user_id=1, age=25, weight_kg=60, height_cm=165,
                       daily_calorie_target=1800, health_goal="weight_loss"),
            UserProfile(user_id=2, age=35, weight_kg=75, height_cm=175,
                       daily_calorie_target=2000, health_goal="maintenance"),
            UserProfile(user_id=3, age=28, weight_kg=85, height_cm=180,
                       daily_calorie_target=3000, health_goal="muscle_gain"),
            UserProfile(user_id=4, age=32, weight_kg=70, height_cm=170,
                       daily_calorie_target=2000, health_goal="maintenance"),
            UserProfile(user_id=5, age=26, weight_kg=55, height_cm=160,
                       daily_calorie_target=1600, health_goal="weight_loss"),
        ]
        return users
    
    def test_segmentation_initialization(self):
        """Test UserSegmentation initialization."""
        seg = UserSegmentation(n_clusters=5)
        assert seg.n_clusters == 5
        assert not seg.fitted
        assert seg.cache_dir.exists()
    
    def test_extract_features_shape(self, sample_users):
        """Test feature extraction produces correct shape."""
        seg = UserSegmentation()
        features = seg.extract_features(sample_users)
        assert features.shape == (5, 12)  # 5 users, expanded profile features
        assert features.dtype == np.float32
    
    def test_extract_features_values(self):
        """Test feature extraction produces correct values."""
        user = UserProfile(
            user_id=1, age=30, weight_kg=70, height_cm=170,
            daily_calorie_target=2000, health_goal="maintenance",
            allergies=["peanut", "shellfish"],
            gender="M",
            physical_activity_level="Very Active",
            dietary_restrictions=["vegan"],
            budget_vnd_max=90000,
            maintenance_calories=2500,
            daily_caloric_surplus=-500,
        )
        seg = UserSegmentation()
        features = seg.extract_features([user])
        
        # Check expanded features.
        assert features[0, 0] == 30  # age
        assert abs(features[0, 1] - 24.22) < 0.1  # BMI
        assert features[0, 2] == 2000  # calorie_target
        assert features[0, 3] == 90000  # budget
        assert features[0, 4] == 2500  # maintenance calories
        assert features[0, 5] == -500  # daily surplus
        assert features[0, 6] == 2  # num_allergies
        assert features[0, 7] == 2  # maintenance goal encoded
        assert features[0, 8] == 4  # very active
        assert features[0, 9] == 3  # vegan
        assert features[0, 10] == 1  # male
        assert abs(features[0, 11] - 0.8) < 0.01

    def test_extract_legacy_features_for_cached_models(self):
        """Old cached demo models still receive the original 5-feature shape."""
        user = UserProfile(
            user_id=1, age=30, weight_kg=70, height_cm=170,
            daily_calorie_target=2000, health_goal="maintenance",
            allergies=["peanut", "shellfish"],
            dietary_restrictions=["vegan"],
        )
        seg = UserSegmentation()
        features = seg.extract_features([user], feature_count=5)

        assert features.shape == (1, 5)
        assert features[0, 0] == 30
        assert abs(features[0, 1] - 24.22) < 0.1
        assert features[0, 2] == 2000
        assert features[0, 3] == 2
        assert features[0, 4] == 2
    
    def test_fit_model(self, sample_users):
        """Test model fitting."""
        seg = UserSegmentation(n_clusters=5)
        stats = seg.fit(sample_users)
        
        assert seg.fitted
        assert stats["n_samples"] == 5
        assert stats["n_clusters"] == 5
        assert stats["inertia"] >= 0
        assert len(stats["cluster_sizes"]) == 5
    
    def test_predict_single_user(self, sample_users):
        """Test prediction for a single user."""
        seg = UserSegmentation(n_clusters=5)
        seg.fit(sample_users)
        
        new_user = UserProfile(
            user_id=10, age=30, weight_kg=70, height_cm=170,
            daily_calorie_target=2000, health_goal="maintenance"
        )
        assignment = seg.predict(new_user)
        
        assert isinstance(assignment, ClusterAssignment)
        assert assignment.user_id == 10
        assert 0 <= assignment.cluster_id < 5
        assert assignment.segment_name in get_segment_names()
        assert assignment.distance_to_centroid >= 0
    
    def test_predict_batch(self, sample_users):
        """Test batch prediction."""
        seg = UserSegmentation(n_clusters=5)
        seg.fit(sample_users)
        
        new_users = [
            UserProfile(user_id=10, age=30, weight_kg=70, height_cm=170,
                       daily_calorie_target=2000, health_goal="maintenance"),
            UserProfile(user_id=11, age=25, weight_kg=60, height_cm=165,
                       daily_calorie_target=1800, health_goal="weight_loss"),
        ]
        assignments = seg.predict_batch(new_users)
        
        assert len(assignments) == 2
        assert all(isinstance(a, ClusterAssignment) for a in assignments)
        assert assignments[0].user_id == 10
        assert assignments[1].user_id == 11
    
    def test_predict_without_fit_raises_error(self):
        """Test that predicting without fitting raises error."""
        seg = UserSegmentation()
        user = UserProfile(
            user_id=1, age=30, weight_kg=70, height_cm=170,
            daily_calorie_target=2000, health_goal="maintenance"
        )
        with pytest.raises(ValueError, match="Model not fitted"):
            seg.predict(user)
    
    def test_get_cluster_profiles(self, sample_users):
        """Test generating cluster profiles."""
        seg = UserSegmentation(n_clusters=5)
        seg.fit(sample_users)
        
        profiles = seg.get_cluster_profiles(sample_users)
        
        assert isinstance(profiles, dict)
        for cluster_id, profile in profiles.items():
            assert 0 <= cluster_id < 5
            assert profile.cluster_id == cluster_id
            assert profile.segment_name in get_segment_names()
            assert profile.num_users >= 0
            assert profile.avg_age >= 0
            assert profile.avg_bmi >= 0
    
    def test_health_goal_encoding(self):
        """Test health goal encoding."""
        seg = UserSegmentation()
        
        user_loss = UserProfile(
            user_id=1, age=30, weight_kg=70, height_cm=170,
            daily_calorie_target=2000, health_goal="weight_loss"
        )
        user_maint = UserProfile(
            user_id=2, age=30, weight_kg=70, height_cm=170,
            daily_calorie_target=2000, health_goal="maintenance"
        )
        user_gain = UserProfile(
            user_id=3, age=30, weight_kg=70, height_cm=170,
            daily_calorie_target=2000, health_goal="muscle_gain"
        )
        
        features_loss = seg.extract_features([user_loss])
        features_maint = seg.extract_features([user_maint])
        features_gain = seg.extract_features([user_gain])
        
        assert features_loss[0, 7] == 1
        assert features_maint[0, 7] == 2
        assert features_gain[0, 7] == 3
    
    def test_cache_and_load_model(self, sample_users, tmp_path):
        """Test caching and loading model."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        
        seg1 = UserSegmentation(n_clusters=5, cache_dir=str(cache_dir))
        seg1.fit(sample_users)
        seg1.cache_model("test_model")
        
        # Load in new instance
        seg2 = UserSegmentation(n_clusters=5, cache_dir=str(cache_dir))
        seg2.load_cached_model("test_model")
        
        assert seg2.fitted
        
        # Verify predictions are consistent
        user = UserProfile(
            user_id=10, age=30, weight_kg=70, height_cm=170,
            daily_calorie_target=2000, health_goal="maintenance"
        )
        pred1 = seg1.predict(user)
        pred2 = seg2.predict(user)
        
        assert pred1.cluster_id == pred2.cluster_id
        assert pred1.segment_name == pred2.segment_name


class TestClusterAssignment:
    """Test ClusterAssignment dataclass."""
    
    def test_cluster_assignment_creation(self):
        """Test creating a cluster assignment."""
        assignment = ClusterAssignment(
            user_id=1,
            cluster_id=2,
            segment_name="health_focused",
            distance_to_centroid=0.5
        )
        assert assignment.user_id == 1
        assert assignment.cluster_id == 2
        assert assignment.segment_name == "health_focused"
    
    def test_cluster_assignment_repr(self):
        """Test string representation."""
        assignment = ClusterAssignment(
            user_id=1,
            cluster_id=2,
            segment_name="health_focused",
            distance_to_centroid=0.5
        )
        repr_str = repr(assignment)
        assert "user=1" in repr_str
        assert "cluster=2" in repr_str


class TestMenuTemplates:
    """Test menu templates."""
    
    def test_menu_templates_exist(self):
        """Test all segment names have templates."""
        segment_names = get_segment_names()
        assert len(segment_names) == 5
        assert "budget_conscious" in segment_names
        assert "health_focused" in segment_names
        assert "performance_athlete" in segment_names
        assert "balanced_lifestyle" in segment_names
        assert "premium_wellness" in segment_names
    
    def test_menu_template_structure(self):
        """Test menu template has required fields."""
        for segment, template in MENU_TEMPLATES.items():
            assert "segment_name" in template
            assert "description" in template
            assert "daily_budget_vnd" in template
            assert "cuisine_preferences" in template
            assert "priority_metrics" in template
            assert "protein_target_ratio" in template
            assert "carbs_target_ratio" in template
            assert "fat_target_ratio" in template
    
    def test_macro_ratios_sum_to_one(self):
        """Test macro ratios sum to 1.0 for each segment."""
        for segment, template in MENU_TEMPLATES.items():
            total = (template["protein_target_ratio"] +
                    template["carbs_target_ratio"] +
                    template["fat_target_ratio"])
            assert abs(total - 1.0) < 0.01  # Allow small floating point error


class TestSegmentPolicies:
    """Test KMeans segment policies passed to CSP."""

    def test_plant_based_active_policy_relaxes_diversity_and_enables_snacks(self):
        user = UserProfile(
            user_id=1,
            age=25,
            weight_kg=65,
            height_cm=170,
            daily_calorie_target=1800,
            health_goal="weight_loss",
            physical_activity_level="Moderately Active",
            dietary_restrictions=["vegan"],
            maintenance_calories=2300,
            daily_caloric_surplus=-500,
        )

        policy = get_segment_policy("balanced_lifestyle", user)

        assert policy["plant_protein_as_core"] is True
        assert policy["enable_snack_from_kcal"] == 1600.0
        assert policy["diversity_penalty_weight"] <= 0.45
        assert policy["macro_stability_weight"] >= 1.3

    def test_apply_segment_policy_to_csp_profile(self):
        user = UserProfile(
            user_id=1,
            age=30,
            weight_kg=70,
            height_cm=170,
            daily_calorie_target=2800,
            health_goal="muscle_gain",
        )
        policy = get_segment_policy("performance_athlete", user)
        csp_profile = {
            "daily_calorie_target": 2800,
            "budget_vnd_max": 150000,
            "macro_ratios": {"protein": 0.35, "fat": 0.20, "carbs": 0.45},
            "exclude_snacks": True,
        }

        tuned = apply_segment_policy_to_csp_profile(csp_profile, policy)

        assert tuned["segment_name"] == "performance_athlete"
        assert tuned["policy_name"] == "high_calorie_distribution"
        assert tuned["enable_snack_from_kcal"] == 2200.0
        assert tuned["csp_time_budget_seconds"] >= 4.0
