"""Data schemas for user segmentation."""
from dataclasses import dataclass, field
from typing import List


@dataclass
class UserProfile:
    """User profile for segmentation feature extraction."""
    user_id: int
    age: int
    weight_kg: float
    height_cm: float
    daily_calorie_target: float
    health_goal: str  # "weight_loss", "maintenance", "muscle_gain"
    allergies: List[str] = field(default_factory=list)
    gender: str = "M"
    physical_activity_level: str = "Moderately Active"
    dietary_restrictions: List[str] = field(default_factory=list)
    budget_vnd_max: float = 100000.0
    maintenance_calories: float = 0.0
    daily_caloric_surplus: float = 0.0
    
    @property
    def bmi(self) -> float:
        """Calculate BMI from weight and height."""
        return self.weight_kg / ((self.height_cm / 100) ** 2)


@dataclass
class ClusterAssignment:
    """Result of K-Means cluster assignment."""
    user_id: int
    cluster_id: int
    segment_name: str
    distance_to_centroid: float
    
    def __repr__(self) -> str:
        return (
            f"ClusterAssignment(user={self.user_id}, "
            f"cluster={self.cluster_id}, segment='{self.segment_name}')"
        )


@dataclass
class ClusterProfile:
    """Aggregated profile for a cluster."""
    cluster_id: int
    segment_name: str
    avg_age: float
    avg_bmi: float
    avg_calorie_target: float
    avg_allergies: float
    num_users: int
    
    def __repr__(self) -> str:
        return (
            f"ClusterProfile(cluster={self.cluster_id}, "
            f"segment='{self.segment_name}', users={self.num_users})"
        )
