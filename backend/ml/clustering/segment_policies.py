"""CSP policy knobs derived from user segments and profile context."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from .menu_templates import MENU_TEMPLATES
from .schemas import UserProfile


DEFAULT_POLICY: Dict[str, Any] = {
    "policy_name": "balanced_lifestyle",
    "macro_stability_weight": 1.0,
    "diversity_penalty_weight": 1.0,
    "enable_snack_from_kcal": 2400.0,
    "plant_protein_as_core": False,
    "csp_time_budget_seconds": 3.0,
    "calorie_tolerance_pct": 0.12,
    "macro_tolerance_pct": 0.12,
}


SEGMENT_POLICIES: Dict[str, Dict[str, Any]] = {
    "budget_conscious": {
        "policy_name": "budget_conscious",
        "diversity_penalty_weight": 0.85,
        "enable_snack_from_kcal": 2600.0,
        "csp_time_budget_seconds": 3.0,
    },
    "health_focused": {
        "policy_name": "health_focused",
        "macro_stability_weight": 1.2,
        "diversity_penalty_weight": 1.05,
        "csp_time_budget_seconds": 3.5,
    },
    "performance_athlete": {
        "policy_name": "performance_athlete",
        "macro_stability_weight": 1.35,
        "enable_snack_from_kcal": 2200.0,
        "csp_time_budget_seconds": 4.0,
    },
    "balanced_lifestyle": {
        "policy_name": "balanced_lifestyle",
    },
    "premium_wellness": {
        "policy_name": "premium_wellness",
        "macro_stability_weight": 1.15,
        "diversity_penalty_weight": 1.15,
        "csp_time_budget_seconds": 3.5,
    },
}


def _normalized_restrictions(user: UserProfile) -> set[str]:
    return {
        str(item).strip().lower()
        for item in (user.dietary_restrictions or [])
        if str(item).strip()
    }


def _activity_rank(activity_level: str | None) -> int:
    return {
        "sedentary": 1,
        "lightly active": 2,
        "moderately active": 3,
        "very active": 4,
    }.get(str(activity_level or "").strip().lower(), 3)


def _merge_policy(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        merged[key] = value
    return merged


def get_segment_policy(segment_name: str, user: UserProfile) -> Dict[str, Any]:
    """Return CSP tuning parameters for a segment, adjusted by user context.

    KMeans provides the broad behavioral group. Profile rules then refine the
    group for hard nutrition realities such as plant-based protein, high target
    calories, and strong calorie deficits.
    """
    template = MENU_TEMPLATES.get(segment_name, MENU_TEMPLATES["balanced_lifestyle"])
    policy = _merge_policy(DEFAULT_POLICY, SEGMENT_POLICIES.get(segment_name, {}))
    policy["segment_name"] = segment_name
    policy["template_name"] = template["segment_name"]
    policy["base_macro_ratios"] = {
        "protein": float(template["protein_target_ratio"]),
        "fat": float(template["fat_target_ratio"]),
        "carbs": float(template["carbs_target_ratio"]),
    }

    restrictions = _normalized_restrictions(user)
    activity_rank = _activity_rank(user.physical_activity_level)
    daily_target = float(user.daily_calorie_target or 0.0)
    budget = float(user.budget_vnd_max or 0.0)
    surplus = float(user.daily_caloric_surplus or 0.0)

    if {"vegetarian", "vegan"}.intersection(restrictions):
        policy = _merge_policy(policy, {
            "policy_name": "plant_based_active" if activity_rank >= 3 else "plant_based_balanced",
            "macro_stability_weight": max(float(policy["macro_stability_weight"]), 1.3),
            "diversity_penalty_weight": min(float(policy["diversity_penalty_weight"]), 0.45),
            "enable_snack_from_kcal": min(float(policy["enable_snack_from_kcal"]), 1600.0),
            "plant_protein_as_core": True,
            "csp_time_budget_seconds": max(float(policy["csp_time_budget_seconds"]), 7.0 if daily_target >= 2200.0 else 5.0),
            "calorie_tolerance_pct": max(float(policy["calorie_tolerance_pct"]), 0.18 if daily_target >= 2200.0 else 0.15),
            "macro_tolerance_pct": max(float(policy["macro_tolerance_pct"]), 0.22 if daily_target >= 2200.0 else 0.18),
        })
    elif restrictions and daily_target >= 2200.0:
        policy = _merge_policy(policy, {
            "policy_name": "restricted_high_calorie_distribution",
            "macro_stability_weight": max(float(policy["macro_stability_weight"]), 1.15),
            "enable_snack_from_kcal": min(float(policy["enable_snack_from_kcal"]), 2200.0),
            "csp_time_budget_seconds": max(float(policy["csp_time_budget_seconds"]), 5.0),
            "calorie_tolerance_pct": max(float(policy["calorie_tolerance_pct"]), 0.15),
            "macro_tolerance_pct": max(float(policy["macro_tolerance_pct"]), 0.15),
        })

    if daily_target >= 2600.0:
        policy = _merge_policy(policy, {
            "policy_name": "high_calorie_distribution",
            "macro_stability_weight": max(float(policy["macro_stability_weight"]), 1.25),
            "enable_snack_from_kcal": min(float(policy["enable_snack_from_kcal"]), 2200.0),
            "csp_time_budget_seconds": max(float(policy["csp_time_budget_seconds"]), 4.0),
        })

    if budget and budget <= 70000.0:
        policy = _merge_policy(policy, {
            "policy_name": "budget_constrained",
            "diversity_penalty_weight": min(float(policy["diversity_penalty_weight"]), 0.75),
            "enable_snack_from_kcal": max(float(policy["enable_snack_from_kcal"]), 2400.0),
        })

    if surplus <= -300.0:
        policy = _merge_policy(policy, {
            "macro_stability_weight": max(float(policy["macro_stability_weight"]), 1.25),
        })

    return policy


def apply_segment_policy_to_csp_profile(csp_profile: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """Attach policy knobs to the CSP profile without hiding original fields."""
    tuned = deepcopy(csp_profile)
    for key in (
        "segment_name",
        "policy_name",
        "macro_stability_weight",
        "diversity_penalty_weight",
        "enable_snack_from_kcal",
        "plant_protein_as_core",
        "csp_time_budget_seconds",
        "calorie_tolerance_pct",
        "macro_tolerance_pct",
    ):
        if key in policy:
            tuned[key] = policy[key]
    return tuned
