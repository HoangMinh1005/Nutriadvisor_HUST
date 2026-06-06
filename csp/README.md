# CSP Module

Contains Chapter 3 meal-scheduling constraints and solver code.

Suggested files:
- constraints.py
- scheduler.py
- objective.py

python -c "
from csp import MealScheduler
user_profile = {
    'daily_calorie_target': 1200,
    'macro_ratios': {'protein': 0.3, 'fat': 0.3, 'carbs': 0.4},
    'allergies': ['vit', 'duck'],
    'budget_vnd_max': 120000,
    'maximize_nutrients': ['protein']
}
scheduler = MealScheduler(user_profile=user_profile, db_url='')
result = scheduler.solve_with_relaxation()
print('Thành công:', result['feasible'])
print('Điểm chất lượng:', result.get('score'))
print('Số lần nới lỏng:', result.get('relaxation_attempts'))
import json; print(json.dumps(result.get('meal_plan')[:1], ensure_ascii=False, indent=2))  # In thử thực đơn Ngày 1
"