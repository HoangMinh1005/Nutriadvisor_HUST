"""CSP Meal Planning Module for NutriAdvisor.

Provides constraint satisfaction and optimization for 7-day meal schedules.
"""
from __future__ import annotations

from .scheduler import MealScheduler
from .constraints import NutrientConstraints

__all__ = ["MealScheduler", "NutrientConstraints"]
