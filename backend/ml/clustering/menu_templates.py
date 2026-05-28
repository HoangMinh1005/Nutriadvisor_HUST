"""Menu templates and recommendations for each user segment."""
from typing import Dict, List


MENU_TEMPLATES: Dict[str, Dict] = {
    "budget_conscious": {
        "segment_name": "Budget Conscious",
        "description": "Cost-effective, nutritious meals for budget-aware users",
        "daily_budget_vnd": 50000,
        "cuisine_preferences": ["Vietnamese", "Asian", "Local"],
        "priority_metrics": ["cost_efficiency", "calorie_density"],
        "example_foods": ["rice", "beans", "seasonal vegetables"],
        "suggested_meal_count": 3,
        "protein_target_ratio": 0.25,
        "carbs_target_ratio": 0.50,
        "fat_target_ratio": 0.25
    },
    
    "health_focused": {
        "segment_name": "Health Focused",
        "description": "Nutrition-optimized meals for health-conscious users",
        "daily_budget_vnd": 150000,
        "cuisine_preferences": ["Mediterranean", "Organic", "Balanced"],
        "priority_metrics": ["nutrient_balance", "micronutrients"],
        "example_foods": ["salmon", "broccoli", "berries", "nuts"],
        "suggested_meal_count": 4,
        "protein_target_ratio": 0.30,
        "carbs_target_ratio": 0.40,
        "fat_target_ratio": 0.30
    },
    
    "performance_athlete": {
        "segment_name": "Performance Athlete",
        "description": "Macro-optimized meals for athletic performance",
        "daily_budget_vnd": 200000,
        "cuisine_preferences": ["High-Protein", "Muscle-Building", "Recovery"],
        "priority_metrics": ["macro_optimization", "protein_content"],
        "example_foods": ["lean meat", "eggs", "greek yogurt", "complex carbs"],
        "suggested_meal_count": 5,
        "protein_target_ratio": 0.35,
        "carbs_target_ratio": 0.45,
        "fat_target_ratio": 0.20
    },
    
    "balanced_lifestyle": {
        "segment_name": "Balanced Lifestyle",
        "description": "Diverse, balanced meals for variety-seeking users",
        "daily_budget_vnd": 100000,
        "cuisine_preferences": ["Diverse", "International", "Exploratory"],
        "priority_metrics": ["variety", "balance", "enjoyment"],
        "example_foods": ["various proteins", "whole grains", "vegetables"],
        "suggested_meal_count": 3,
        "protein_target_ratio": 0.30,
        "carbs_target_ratio": 0.45,
        "fat_target_ratio": 0.25
    },
    
    "premium_wellness": {
        "segment_name": "Premium Wellness",
        "description": "Gourmet, organic meals for wellness-oriented users",
        "daily_budget_vnd": 300000,
        "cuisine_preferences": ["Gourmet", "Organic", "Premium", "Specialty"],
        "priority_metrics": ["taste", "quality", "sustainability"],
        "example_foods": ["grass-fed beef", "organic vegetables", "specialty oils"],
        "suggested_meal_count": 4,
        "protein_target_ratio": 0.30,
        "carbs_target_ratio": 0.40,
        "fat_target_ratio": 0.30
    }
}


def get_menu_template(segment_name: str) -> Dict:
    """
    Get menu template for a specific segment.
    
    Args:
        segment_name: Name of the segment (e.g., 'budget_conscious')
        
    Returns:
        Dictionary with menu template configuration
    """
    return MENU_TEMPLATES.get(segment_name, MENU_TEMPLATES["balanced_lifestyle"])


def get_all_templates() -> Dict[str, Dict]:
    """Get all menu templates."""
    return MENU_TEMPLATES.copy()


def get_segment_names() -> List[str]:
    """Get all available segment names."""
    return list(MENU_TEMPLATES.keys())
