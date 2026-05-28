"""K-Means user segmentation for personalized recommendations."""
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from typing import List, Dict, Tuple
import pickle
from pathlib import Path

from .schemas import UserProfile, ClusterAssignment, ClusterProfile


class UserSegmentation:
    """
    Segment users into K clusters based on profile features.
    
    Features used:
    - Age
    - BMI (Body Mass Index)
    - Daily calorie target
    - Number of allergies
    - Health goal (encoded: 1=weight_loss, 2=maintenance, 3=muscle_gain)
    """
    
    SEGMENT_NAMES = [
        "budget_conscious",      # Cluster 0
        "health_focused",         # Cluster 1
        "performance_athlete",    # Cluster 2
        "balanced_lifestyle",     # Cluster 3
        "premium_wellness"        # Cluster 4
    ]
    
    HEALTH_GOAL_MAP = {
        "weight_loss": 1,
        "maintenance": 2,
        "muscle_gain": 3
    }
    
    def __init__(self, n_clusters: int = 5, cache_dir: str = "data/ml/clustering"):
        """
        Initialize K-Means segmentation model.
        
        Args:
            n_clusters: Number of user segments (default: 5)
            cache_dir: Directory for caching model artifacts
        """
        self.n_clusters = n_clusters
        self.kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        self.scaler = StandardScaler()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fitted = False
    
    def extract_features(self, users: List[UserProfile]) -> np.ndarray:
        """
        Extract feature matrix from user profiles.
        
        Features: [age, BMI, daily_calorie_target, num_allergies, health_goal_encoded]
        
        Args:
            users: List of UserProfile objects
            
        Returns:
            Feature matrix of shape (n_users, 5)
        """
        features = []
        for user in users:
            age = user.age
            bmi = user.bmi
            cal_target = user.daily_calorie_target
            num_allergies = len(user.allergies)
            goal_encoded = self.HEALTH_GOAL_MAP.get(user.health_goal, 2)
            
            features.append([age, bmi, cal_target, num_allergies, goal_encoded])
        
        return np.array(features, dtype=np.float32)
    
    def fit(self, users: List[UserProfile]) -> Dict:
        """
        Fit K-Means model on user features.
        
        Args:
            users: List of UserProfile objects
            
        Returns:
            Dictionary with fitting statistics
        """
        X = self.extract_features(users)
        X_scaled = self.scaler.fit_transform(X)
        self.kmeans.fit(X_scaled)
        self.fitted = True
        
        # Calculate inertia and silhouette for model quality
        inertia = self.kmeans.inertia_
        
        # Calculate cluster sizes
        labels = self.kmeans.labels_
        cluster_sizes = np.bincount(labels, minlength=self.n_clusters)
        
        stats = {
            "n_samples": len(users),
            "n_clusters": self.n_clusters,
            "inertia": float(inertia),
            "cluster_sizes": cluster_sizes.tolist(),
            "fitted": True
        }
        
        return stats
    
    def predict(self, user: UserProfile) -> ClusterAssignment:
        """
        Predict cluster assignment for a single user.
        
        Args:
            user: UserProfile object
            
        Returns:
            ClusterAssignment with cluster_id and segment_name
        """
        if not self.fitted:
            raise ValueError("Model not fitted. Call fit() first.")
        
        X = self.extract_features([user])
        X_scaled = self.scaler.transform(X)
        
        cluster_id = int(self.kmeans.predict(X_scaled)[0])
        distance = float(
            np.linalg.norm(X_scaled[0] - self.kmeans.cluster_centers_[cluster_id])
        )
        segment_name = self.SEGMENT_NAMES[cluster_id]
        
        return ClusterAssignment(
            user_id=user.user_id,
            cluster_id=cluster_id,
            segment_name=segment_name,
            distance_to_centroid=distance
        )
    
    def predict_batch(self, users: List[UserProfile]) -> List[ClusterAssignment]:
        """
        Predict cluster assignments for multiple users.
        
        Args:
            users: List of UserProfile objects
            
        Returns:
            List of ClusterAssignment objects
        """
        if not self.fitted:
            raise ValueError("Model not fitted. Call fit() first.")
        
        X = self.extract_features(users)
        X_scaled = self.scaler.transform(X)
        
        cluster_ids = self.kmeans.predict(X_scaled)
        distances = np.linalg.norm(
            X_scaled - self.kmeans.cluster_centers_[cluster_ids],
            axis=1
        )
        
        assignments = []
        for user, cluster_id, distance in zip(users, cluster_ids, distances):
            assignment = ClusterAssignment(
                user_id=user.user_id,
                cluster_id=int(cluster_id),
                segment_name=self.SEGMENT_NAMES[int(cluster_id)],
                distance_to_centroid=float(distance)
            )
            assignments.append(assignment)
        
        return assignments
    
    def get_cluster_profiles(self, users: List[UserProfile]) -> Dict[int, ClusterProfile]:
        """
        Generate aggregated profiles for each cluster.
        
        Args:
            users: List of UserProfile objects (must be fitted)
            
        Returns:
            Dictionary mapping cluster_id to ClusterProfile
        """
        assignments = self.predict_batch(users)
        cluster_profiles = {}
        
        for cluster_id in range(self.n_clusters):
            cluster_users = [
                users[i] for i, assign in enumerate(assignments)
                if assign.cluster_id == cluster_id
            ]
            
            if cluster_users:
                avg_age = np.mean([u.age for u in cluster_users])
                avg_bmi = np.mean([u.bmi for u in cluster_users])
                avg_cal = np.mean([u.daily_calorie_target for u in cluster_users])
                avg_allergies = np.mean([len(u.allergies) for u in cluster_users])
                
                profile = ClusterProfile(
                    cluster_id=cluster_id,
                    segment_name=self.SEGMENT_NAMES[cluster_id],
                    avg_age=float(avg_age),
                    avg_bmi=float(avg_bmi),
                    avg_calorie_target=float(avg_cal),
                    avg_allergies=float(avg_allergies),
                    num_users=len(cluster_users)
                )
                cluster_profiles[cluster_id] = profile
        
        return cluster_profiles
    
    def cache_model(self, name: str = "user_segmentation"):
        """
        Save fitted model and scaler to disk.
        
        Args:
            name: Name for cached files (default: 'user_segmentation')
        """
        if not self.fitted:
            raise ValueError("Model not fitted. Cannot cache unfitted model.")
        
        kmeans_path = self.cache_dir / f"{name}_kmeans.pkl"
        scaler_path = self.cache_dir / f"{name}_scaler.pkl"
        
        with open(kmeans_path, "wb") as f:
            pickle.dump(self.kmeans, f)
        
        with open(scaler_path, "wb") as f:
            pickle.dump(self.scaler, f)
    
    def load_cached_model(self, name: str = "user_segmentation"):
        """
        Load cached model and scaler from disk.
        
        Args:
            name: Name of cached files to load
        """
        kmeans_path = self.cache_dir / f"{name}_kmeans.pkl"
        scaler_path = self.cache_dir / f"{name}_scaler.pkl"
        
        with open(kmeans_path, "rb") as f:
            self.kmeans = pickle.load(f)
        
        with open(scaler_path, "rb") as f:
            self.scaler = pickle.load(f)
        
        self.fitted = True
