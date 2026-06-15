from backend.app.main import _meal_plan_slot_shape_stale, _target_requires_snack


THREE_MEAL_PLAN = [{
    "day": 1,
    "meals": [
        {"meal_type": "breakfast"},
        {"meal_type": "lunch"},
        {"meal_type": "dinner"},
    ],
}]

FOUR_MEAL_PLAN = [{
    "day": 1,
    "meals": [
        {"meal_type": "breakfast"},
        {"meal_type": "lunch"},
        {"meal_type": "snack"},
        {"meal_type": "dinner"},
    ],
}]


def test_low_calorie_target_marks_existing_snack_plan_stale():
    assert _meal_plan_slot_shape_stale(FOUR_MEAL_PLAN, 1800, [], "Moderately Active", 200000)


def test_high_calorie_target_marks_three_meal_plan_stale():
    assert _meal_plan_slot_shape_stale(THREE_MEAL_PLAN, 3000, [], "Moderately Active", 200000)


def test_matching_slot_shape_is_not_stale():
    assert not _meal_plan_slot_shape_stale(THREE_MEAL_PLAN, 1800, [], "Moderately Active", 200000)
    assert not _meal_plan_slot_shape_stale(FOUR_MEAL_PLAN, 3000, [], "Moderately Active", 200000)


def test_dietary_modes_use_lower_snack_thresholds():
    assert _target_requires_snack(1800, ["vegetarian"], "Moderately Active", 200000)
    assert _target_requires_snack(2300, ["halal"], "Moderately Active", 200000)
