"""K-Means user segmentation module."""

from .schemas import UserProfile, ClusterAssignment, ClusterProfile
from .user_segmentation import UserSegmentation
from .menu_templates import (
    MENU_TEMPLATES,
    get_menu_template,
    get_all_templates,
    get_segment_names
)

__all__ = [
    "UserProfile",
    "ClusterAssignment",
    "ClusterProfile",
    "UserSegmentation",
    "MENU_TEMPLATES",
    "get_menu_template",
    "get_all_templates",
    "get_segment_names"
]
